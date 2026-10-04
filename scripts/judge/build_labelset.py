"""Build a label set: full rollouts, segmented, for the labelling UI (no judge output, so labelling stays blind).

    uv run python scripts/judge/build_labelset.py logs/03-pilot/v4flash/promptB-5att \
        --keys lcb_oneoff_noflag:lcbhard_86:e1,lcb_conflicting_noflag:lcbhard_102:e1 \
        --name uitest

One work item = one rollout (`<task>:<sample_id>:e<epoch>`) with all its attempts in order.
`--keys` is a comma list or a file with one key per line; attempt keys (`...:a3`) are
accepted and mapped to their rollout. With `--single-attempts`, each attempt key becomes its
own work item containing only that attempt (its prior feedback is still shown). Segmentation is the judge's (same IDs, loop cutoff
applied). Writes logs/12-judge/labelsets/<name>/data.json.
"""

import argparse
import difflib
import json
from collections import defaultdict
from functools import cache
from pathlib import Path

from datasets import load_dataset

from earh.judge.extract import extract_attempts
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer

ROOT = Path("logs/12-judge/labelsets")
DATASET = "fjzzq2002/impossible_livecodebench"


@cache
def _tests(split: str) -> dict[str, str]:
    """task_id -> test code for one ImpossibleBench split (HF cache)."""
    return {r["task_id"]: r["test"] for r in load_dataset(DATASET, split=split)}


def _call(line: str) -> str:
    """The left side of an assertion (`assert candidate(...)`), used to pair duplicates."""
    return line.split("==")[0].strip()


def altered(task_id: str, split: str) -> list[dict]:
    """The assertions ImpossibleBench altered, from diffing the original and modified tests.

    one-off: an assertion whose expected value was changed (kind "changed", with the original).
    conflicting: an added assertion (kind "added") whose input already has a test; the
    contradicted original is given as "counterpart".

    @param task_id: e.g. "lcbhard_86".
    @param split: "oneoff" or "conflicting".
    @returns: [{kind, modified, original, counterpart}] (strings stripped; None when absent).
    """
    orig = _tests("original")[task_id].splitlines()
    mod = _tests(split)[task_id].splitlines()
    out = []
    sm = difflib.SequenceMatcher(a=orig, b=mod, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        for k, line in enumerate(mod[j1:j2]):
            if not line.strip().startswith("assert"):
                continue
            was = orig[i1 + k] if op == "replace" and i1 + k < i2 else None
            twin = next(
                (
                    o
                    for o in orig
                    if _call(o) == _call(line) and o.strip() != line.strip()
                ),
                None,
            )
            out.append(
                {
                    "kind": "changed" if was else "added",
                    "modified": line.strip(),
                    "original": was.strip() if was else None,
                    "counterpart": None if was else (twin.strip() if twin else None),
                }
            )
    return out


def _keys(spec: str) -> list[str]:
    """Keys from a comma list or a file (one per line), in order, without duplicates."""
    p = Path(spec)
    raw = p.read_text().split() if p.exists() else spec.split(",")
    return list(dict.fromkeys(k.strip() for k in raw if k.strip()))


def _attempt(a) -> dict:
    """One attempt as the UI needs it: context, numbered reasoning, numbered answer."""
    segs, info = reasoning_segments(a)
    # brk: what separates a sentence from the previous one in the raw text (0 same line,
    # 1 newline, 2 blank line), so the UI can rebuild the model's paragraphs.
    brk = [2] + [
        min(2, a.reasoning[p.end : q.start].count("\n"))
        for p, q in zip(segs, segs[1:], strict=False)
    ]
    return {
        "key": a.key,
        "attempt": a.attempt,
        "feedback_before": a.feedback_before,
        "test_output": a.test_output,
        "judge_cutoff": info.get("judge_cutoff"),
        "reasoning": [
            {"id": s.id, "kind": s.kind, "text": s.text, "brk": b}
            for s, b in zip(segs, brk, strict=True)
        ],
        "answer": [
            {"id": s.id, "kind": s.kind, "text": s.text}
            for s in segment_answer(a.answer, a.attempt)
        ],
    }


def main() -> None:
    """Group the requested rollouts' attempts and write the label set."""
    ap = argparse.ArgumentParser()
    ap.add_argument("log_dir")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--single-attempts", action="store_true")
    args = ap.parse_args()
    by_rollout = defaultdict(list)
    for a in extract_attempts(args.log_dir):
        by_rollout[f"{a.task}:{a.sample_id}:e{a.epoch}"].append(a)
    items = []
    for k in _keys(args.keys):
        r = ":".join(k.split(":")[:3])
        atts = sorted(by_rollout.get(r, []), key=lambda a: a.attempt)
        if args.single_attempts:
            atts = [a for a in atts if a.key == k]
            r = k  # the work item is the attempt
        if not atts:
            raise SystemExit(f"not found in {args.log_dir}: {k}")
        if any(i["rollout"] == r for i in items):
            continue
        items.append(
            {
                "rollout": r,
                "split": atts[0].split,
                "task_prompt": atts[0].task_prompt,
                "altered": altered(atts[0].sample_id, atts[0].split),
                "attempts": [_attempt(a) for a in atts],
            }
        )
    d = ROOT / args.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(
        json.dumps({"name": args.name, "source": args.log_dir, "items": items})
    )
    n = sum(len(i["attempts"]) for i in items)
    print(f"wrote {d / 'data.json'}: {len(items)} rollouts, {n} attempts")


if __name__ == "__main__":
    main()
