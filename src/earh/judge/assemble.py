"""Assemble judge outputs into per-attempt judgments with derived EA and cheat measures.

Joins judge logs (tags by unit) with the attempts they came from, re-segmenting the
reasoning so every tagged ID maps to text and a relative position.
"""

from __future__ import annotations

from collections import defaultdict

from inspect_ai.log import list_eval_logs, read_eval_log

from earh.judge.extract import Attempt
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer


def _first(tags: list[dict], label: str) -> float | None:
    """Relative position of the first tag with this label, if any."""
    return next((t["rel_pos"] for t in tags if t["label"] == label), None)


def load_judge_tags(judge_log_dir: str) -> dict[str, dict]:
    """Collect tags per attempt from judge logs.

    @param judge_log_dir: Directory of judge-task .eval logs.
    @returns: attempt_key -> {"tags": [...], "summary": {...} | None, "invalid_units": [...],
        "units": n}.
    """
    out: dict[str, dict] = defaultdict(
        lambda: {"tags": [], "summary": None, "invalid_units": [], "units": 0}
    )
    for info in list_eval_logs(judge_log_dir):
        for s in read_eval_log(info).samples or []:
            j = s.metadata.get("judge") or next(iter(s.scores.values())).metadata
            rec = out[s.metadata["attempt_key"]]
            rec["units"] += 1
            rec["tags"] += j["tags"]
            if j.get("summary") is not None:
                rec["summary"] = j["summary"]
            if not j["valid"]:
                rec["invalid_units"].append(s.id)
    return dict(out)


def assemble(attempts: list[Attempt], judged: dict[str, dict]) -> list[dict]:
    """Per-attempt judgment records with text, positions, and EA / cheat measures.

    @param attempts: Attempts from earh.judge.extract (same logs the units were built from).
    @param judged: Output of load_judge_tags.
    @returns: One record per judged attempt (attempts with no judge output are skipped).
    """
    records = []
    for a in attempts:
        j = judged.get(a.key)
        if j is None:
            continue
        segs, info = reasoning_segments(a)
        by_id = {s.id: s for s in segs} | {
            s.id: s for s in segment_answer(a.answer, a.attempt)
        }
        n = len(segs)
        order = {s.id: i for i, s in enumerate(segs)}
        tags = []
        for t in j["tags"]:
            seg = by_id.get(t["id"])
            if seg is None:
                continue
            rel = order[t["id"]] / max(1, n - 1) if t["id"] in order else None
            tags.append(
                {
                    **t,
                    "text": seg.text,
                    "start": seg.start,
                    "end": seg.end,
                    "rel_pos": rel,
                }
            )
        tags.sort(key=lambda t: (t["id"][0], t["start"]))
        ea = [t for t in tags if t["label"] == "eval_awareness"]

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
                "ea_count": len(ea),
                "ea_per_100_sentences": 100 * len(ea) / n if n else 0.0,
                "ea_framings": sorted({t["framing"] for t in ea}),
                "ea_first_rel_pos": _first(tags, "eval_awareness"),
                "contradiction_first_rel_pos": _first(tags, "contradiction"),
                "cheat_decision_first_rel_pos": _first(tags, "cheat_decision"),
                "cheat_summary": j["summary"],
                "invalid_units": j["invalid_units"],
                "n_units": j["units"],
                "tags": tags,
            }
        )
    return records
