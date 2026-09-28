"""Detect attempts whose reasoning degenerated into repetition before hitting the token cap.

A truncated attempt (stop_reason == max_tokens) usually ends in a loop: the same
arithmetic, symbols, or phrases repeated until the cap. We measure repetitiveness by
zlib compression ratio (compressed / raw bytes), which works regardless of spacing or
wording: repetitive text compresses extremely well.

Calibration (phase 1, 2026-09-27): tail-20k-char ratio of the 12 truncated attempts
= 0.002–0.068; of 1,263 normal attempts ≥ 30k chars: min 0.187, p1 0.276, median 0.33.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

TAIL_CHARS = 20_000
# Tried smallest-first: exact loops show at 4k (precise start); circular reasoning
# (long cycles) only at 20k, where the start estimate is up to ~one window early.
WINDOWS = (4_000, 20_000)
STEP_CHARS = 1_000
REPETITIVE = 0.12  # compression ratio below this = degenerate repetition
EXACT_LOOP = 0.02  # below this = exact loop; between the two = circular reasoning


@dataclass(frozen=True)
class Degeneration:
    """Repetition diagnosis for one reasoning text."""

    # "exact_loop" | "circular" | "none"
    kind: str
    # compression ratio of the last TAIL_CHARS chars
    tail_compression: float
    # char offset where sustained repetition begins
    loop_start: int | None
    # loop_start / len(text)
    loop_start_rel: float | None
    # read reasoning up to here: loop start + one window (keeps all pre-loop text)
    judge_cutoff: int | None


def compression_ratio(text: str) -> float:
    """zlib-compressed size / raw size (lower = more repetitive; 1.0 for empty text)."""
    raw = text.encode()
    return len(zlib.compress(raw, 9)) / len(raw) if raw else 1.0


def diagnose(text: str) -> Degeneration:
    """Classify repetition in reasoning text and locate where the loop starts.

    The tail decides the kind. For the smallest window size in WINDOWS that sees the tail
    as repetitive, the loop start is the first window (stepping STEP_CHARS) from which every
    later window stays below REPETITIVE. judge_cutoff = start + that window's size.

    @param text: Reasoning text of one attempt.
    @returns: Degeneration with kind, tail compression ratio, and estimated loop start.
    """
    tail = compression_ratio(text[-TAIL_CHARS:])
    if tail >= REPETITIVE:
        return Degeneration("none", round(tail, 3), None, None, None)

    loop_start, window = max(0, len(text) - TAIL_CHARS), TAIL_CHARS
    for size in WINDOWS:
        starts = list(range(0, max(1, len(text) - size + 1), STEP_CHARS))
        low = [compression_ratio(text[s : s + size]) < REPETITIVE for s in starts]
        if not low[-1]:
            continue
        first = len(starts) - 1
        while first > 0 and low[first - 1]:
            first -= 1
        loop_start, window = starts[first], size
        break
    kind = "exact_loop" if tail < EXACT_LOOP else "circular"
    return Degeneration(
        kind,
        round(tail, 3),
        loop_start,
        round(loop_start / len(text), 3),
        min(len(text), loop_start + window),
    )
