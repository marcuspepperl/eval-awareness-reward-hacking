"""Assemble judge outputs into per-attempt judgments with derived EA and cheat measures.

Joins judge logs (spans by unit) with the attempts they came from, re-segmenting the
reasoning so every span maps to text and a relative position. Adjacent spans with the
same label (e.g. one occurrence split at a chunk boundary) are merged into one occurrence.
First-only labels (bad_test, cheat_considered) are reported once per chunk; the earliest
across chunks is kept.
"""

from __future__ import annotations

from collections import defaultdict

from inspect_ai.log import list_eval_logs, read_eval_log

from earh.judge.extract import Attempt
from earh.judge.parse import FIRST_ONLY
from earh.judge.units import reasoning_segments
from earh.segment import Segment, segment_answer


def load_judge_spans(
    judge_log_dir: str, passes: set[str] | None = None
) -> dict[str, dict]:
    """Collect spans per attempt from judge logs.

    @param judge_log_dir: Directory of judge-task .eval logs.
    @param passes: Only include units of these passes (e.g. {"B1"}); None = all.
    @returns: attempt_key -> {"spans", "summary", "invalid_units", "units"}.
    """
    out: dict[str, dict] = defaultdict(
        lambda: {"spans": [], "summary": None, "invalid_units": [], "units": 0}
    )
    for info in list_eval_logs(judge_log_dir):
        for s in read_eval_log(info).samples or []:
            if passes and s.metadata["pass"] not in passes:
                continue
            j = s.metadata.get("judge") or next(iter(s.scores.values())).metadata
            rec = out[s.metadata["attempt_key"]]
            rec["units"] += 1
            rec["spans"] += j["spans"]
            if j.get("summary") is not None:
                rec["summary"] = j["summary"]
            if not j["valid"]:
                rec["invalid_units"].append(s.id)
    return dict(out)


def merge_adjacent(spans: list[dict], order: dict[str, int]) -> list[dict]:
    """Merge spans of the same kind whose items are consecutive (e.g. split by a chunk boundary).

    @param spans: Spans with "ids" and "label", from any chunks of one attempt.
    @param order: Item ID -> position in the attempt's item sequence.
    @returns: Spans sorted by position; merged spans keep the first span's attributes.
    """
    ordered = sorted(spans, key=lambda s: (s["label"], order[s["ids"][0]]))
    merged: list[dict] = []
    for s in ordered:
        last = merged[-1] if merged else None
        if (
            last
            and last["label"] == s["label"]
            and order[s["ids"][0]] == order[last["ids"][-1]] + 1
        ):
            last["ids"] = last["ids"] + s["ids"]
            last["end"] = s["end"]
            last["merged"] = last.get("merged", 1) + 1
        else:
            merged.append(dict(s))
    return sorted(merged, key=lambda s: order[s["ids"][0]])


def _describe(
    span: dict, items: dict[str, Segment], order: dict[str, int], n: int
) -> dict:
    """Add text, char offsets, and relative position (reasoning spans only) to a span."""
    segs = [items[i] for i in span["ids"]]
    first = span["ids"][0]
    rel = order[first] / max(1, n - 1) if first.startswith("r") else None
    return {
        **span,
        "text": " ".join(s.text for s in segs),
        "char_start": segs[0].start,
        "char_end": segs[-1].end,
        "rel_pos": rel,
    }


def keep_first(spans: list[dict], order: dict[str, int]) -> list[dict]:
    """Drop all but the earliest span of each first-only label (one per chunk comes in)."""
    seen: set[str] = set()
    out = []
    for s in sorted(spans, key=lambda s: order[s["ids"][0]]):
        if s["label"] in FIRST_ONLY:
            if s["label"] in seen:
                continue
            seen.add(s["label"])
        out.append(s)
    return out


def _first(spans: list[dict], label: str) -> float | None:
    """Relative position of the first span with this label, if any."""
    return next((s["rel_pos"] for s in spans if s["label"] == label), None)


def assemble(attempts: list[Attempt], judged: dict[str, dict]) -> list[dict]:
    """Per-attempt judgment records with text, positions, and EA / cheat measures.

    @param attempts: Attempts from earh.judge.extract (same logs the units were built from).
    @param judged: Output of load_judge_spans.
    @returns: One record per judged attempt (attempts with no judge output are skipped).
    """
    records = []
    for a in attempts:
        j = judged.get(a.key)
        if j is None:
            continue
        segs, info = reasoning_segments(a)
        all_items = segs + segment_answer(a.answer, a.attempt)
        items = {s.id: s for s in all_items}
        order = {s.id: i for i, s in enumerate(all_items)}
        n = len(segs)
        known = [s for s in j["spans"] if all(i in items for i in s["ids"])]
        spans = [
            _describe(s, items, order, n)
            for s in keep_first(merge_adjacent(known, order), order)
        ]
        ea = [s for s in spans if s["label"] == "eval_awareness"]
        ea_sentences = sum(len(s["ids"]) for s in ea)
        records.append(
            {
                "key": a.key,
                "task": a.task,
                "sample_id": a.sample_id,
                "epoch": a.epoch,
                "attempt": a.attempt,
                "split": a.split,
                "passed": a.passed,
                "truncated": a.truncated,
                **info,
                "n_sentences": n,
                "reasoning_chars": len(a.reasoning),
                "ea_occurrences": len(ea),
                "ea_sentences": ea_sentences,
                "ea_share": ea_sentences / n if n else 0.0,
                "ea_framings": sorted({s["framing"] for s in ea}),
                "ea_first_rel_pos": _first(spans, "eval_awareness"),
                "grader_occurrences": sum(s["label"] == "grader" for s in spans),
                "bad_test_first_rel_pos": _first(spans, "bad_test"),
                "cheat_considered_first_rel_pos": _first(spans, "cheat_considered"),
                "cheat_summary": j["summary"],
                "invalid_units": j["invalid_units"],
                "n_units": j["units"],
                "spans": spans,
            }
        )
    return records
