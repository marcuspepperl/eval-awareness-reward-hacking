"""Build a label set: segmented attempts for the labelling UI (no judge output, so labelling stays blind).

    uv run python scripts/judge/build_labelset.py logs/03-pilot/v4flash/promptB-5att \
        --keys lcb_oneoff_noflag:lcbhard_86:e1:a2,lcb_conflicting_noflag:lcbhard_102:e1:a4 \
        --name uitest

Writes logs/12-judge/labelsets/<name>/data.json. `--keys` is a comma list or a file with one
key per line. Segmentation is the judge's (same IDs, loop cutoff applied).
"""

import argparse
import json
from pathlib import Path

from earh.judge.extract import extract_attempts
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer

ROOT = Path("logs/12-judge/labelsets")


def _keys(spec: str) -> list[str]:
    """Keys from a comma list or a file (one per line)."""
    p = Path(spec)
    raw = p.read_text().split() if p.exists() else spec.split(",")
    return [k.strip() for k in raw if k.strip()]


def main() -> None:
    """Extract the requested attempts, segment them, and write the label set."""
    ap = argparse.ArgumentParser()
    ap.add_argument("log_dir")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    want = _keys(args.keys)
    by_key = {a.key: a for a in extract_attempts(args.log_dir)}
    missing = [k for k in want if k not in by_key]
    if missing:
        raise SystemExit(f"keys not found in {args.log_dir}: {missing}")
    out = []
    for k in want:
        a = by_key[k]
        segs, info = reasoning_segments(a)
        out.append(
            {
                "key": a.key,
                "split": a.split,
                "attempt": a.attempt,
                "task_prompt": a.task_prompt,
                "feedback_before": a.feedback_before,
                "test_output": a.test_output,
                "judge_cutoff": info.get("judge_cutoff"),
                "reasoning": [
                    {"id": s.id, "kind": s.kind, "text": s.text} for s in segs
                ],
                "answer": [
                    {"id": s.id, "kind": s.kind, "text": s.text}
                    for s in segment_answer(a.answer, a.attempt)
                ],
            }
        )
    d = ROOT / args.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(
        json.dumps({"name": args.name, "source": args.log_dir, "attempts": out})
    )
    print(f"wrote {d / 'data.json'}: {len(out)} attempts")


if __name__ == "__main__":
    main()
