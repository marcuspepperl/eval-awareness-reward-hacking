"""Segment attempts into ID-labelled items and render them for the judge.

The judge tags items by ID (`r3.0187`, `a3.L38`) instead of quoting text, so every
label maps to an exact location. Segmentation is deterministic; the (id -> text,
char offsets) table is the ground truth for turning judge tags into text and positions.

ID scheme (per attempt k):
  r<k>.<nnnn>   reasoning sentence (or a whole fenced code block inside reasoning)
  a<k>.L<nn>    answer code line (inside a fenced block)
  a<k>.S<nn>    answer prose sentence (outside code blocks)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["sentence", "code_block", "code_line", "prose"]

FENCE = re.compile(r"^\s*```")
# Split after . ! ? (optionally followed by closing quotes/brackets) when whitespace and
# a plausible sentence start follow. Avoids decimals (3.14), method calls (x.append) and
# lowercase continuations ("e.g. the").
SENTENCE_END = re.compile(r"(?<=[.!?])([\"')\]]*)(\s+)(?=[A-Z0-9\"'(\[`*#-])")
CHARS_PER_TOKEN = 4  # rough estimate, only used for chunk sizing


@dataclass(frozen=True)
class Segment:
    """One addressable item: its ID, kind, text, and [start, end) offsets in the source text."""

    id: str
    kind: Kind
    text: str
    start: int
    end: int


def _split_sentences(line: str, offset: int) -> list[tuple[str, int, int]]:
    """Split one non-code line into (text, start, end) sentences with absolute offsets."""
    pieces, pos = [], 0
    for m in SENTENCE_END.finditer(line):
        pieces.append(
            (pos, m.start(2))
        )  # closing quotes/brackets stay with the sentence
        pos = m.end()
    pieces.append((pos, len(line)))
    out = []
    for s, e in pieces:
        text = line[s:e]
        stripped = text.strip()
        if stripped:
            lead = len(text) - len(text.lstrip())
            start = offset + s + lead
            out.append((stripped, start, start + len(stripped)))
    return out


def _lines(text: str) -> list[tuple[str, int]]:
    """Lines of text with their start offsets."""
    out, pos = [], 0
    for line in text.split("\n"):
        out.append((line, pos))
        pos += len(line) + 1
    return out


def segment_reasoning(text: str, attempt: int) -> list[Segment]:
    """Split reasoning into sentences; each fenced code block becomes one item.

    Splits on newlines and sentence punctuation, never merges across newlines, and
    skips blank lines. Over-splitting is acceptable; merging distinct sentences is not.

    @param text: The attempt's reasoning text.
    @param attempt: 1-based attempt number (used in IDs).
    @returns: Segments with IDs r<attempt>.0001, r<attempt>.0002, ...
    """
    items: list[tuple[Kind, str, int, int]] = []
    lines = _lines(text)
    i = 0
    while i < len(lines):
        line, off = lines[i]
        if FENCE.match(line):
            j = i + 1
            while j < len(lines) and not FENCE.match(lines[j][0]):
                j += 1
            end_line, end_off = lines[min(j, len(lines) - 1)]
            end = end_off + len(end_line)
            items.append(("code_block", text[off:end], off, end))
            i = j + 1
            continue
        for s, a, b in _split_sentences(line, off):
            items.append(("sentence", s, a, b))
        i += 1
    return [
        Segment(f"r{attempt}.{n:04d}", kind, t, a, b)
        for n, (kind, t, a, b) in enumerate(items, start=1)
    ]


def segment_answer(text: str, attempt: int) -> list[Segment]:
    """Split the answer into code lines (inside fences) and prose sentences (outside).

    @param text: The attempt's answer text (reasoning excluded).
    @param attempt: 1-based attempt number (used in IDs).
    @returns: Segments with IDs a<attempt>.L01... for code lines and a<attempt>.S01... for prose.
    """
    segs: list[Segment] = []
    n_code = n_prose = 0
    in_code = False
    for line, off in _lines(text):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            if line.strip():
                n_code += 1
                segs.append(
                    Segment(
                        f"a{attempt}.L{n_code:02d}",
                        "code_line",
                        line,
                        off,
                        off + len(line),
                    )
                )
            continue
        for s, a, b in _split_sentences(line, off):
            n_prose += 1
            segs.append(Segment(f"a{attempt}.S{n_prose:02d}", "prose", s, a, b))
    return segs


def render(segments: list[Segment]) -> str:
    """Render segments as '[id] text' lines for the judge (code blocks keep their newlines)."""
    return "\n".join(f"[{s.id}] {s.text}" for s in segments)


def chunk(segments: list[Segment], max_tokens: int = 12_000) -> list[list[Segment]]:
    """Group consecutive segments into chunks under ~max_tokens, never splitting a segment.

    @param segments: Segments in order (IDs are global, so chunks keep them).
    @param max_tokens: Approximate token budget per chunk (chars / 4 estimate).
    @returns: List of chunks; a single oversized segment forms its own chunk.
    """
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    budget = max_tokens * CHARS_PER_TOKEN
    for s in segments:
        cost = len(s.text) + len(s.id) + 4
        if current and size + cost > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(s)
        size += cost
    if current:
        chunks.append(current)
    return chunks
