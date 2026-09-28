"""Print every judged span with one item of context before and after, for precision review.

uv run python scripts/judge/review.py logs/12-judge/pilot10/v2 [--label eval_awareness]
"""

import argparse
import json
from pathlib import Path

from earh.judge.extract import Attempt
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer


def main() -> None:
    """Load judgments + attempts and print spans with context."""
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--label", default=None)
    p.add_argument("--width", type=int, default=220)
    args = p.parse_args()
    run = Path(args.run_dir)
    attempts = {
        a["key"]: Attempt(**a) for a in map(json.loads, (run / "attempts.jsonl").open())
    }
    for r in map(json.loads, (run / "judgments.jsonl").open()):
        a = attempts[r["key"]]
        segs, _ = reasoning_segments(a)
        items = segs + segment_answer(a.answer, a.attempt)
        pos = {s.id: i for i, s in enumerate(items)}
        spans = [s for s in r["spans"] if not args.label or s["label"] == args.label]
        print(f"\n=== {r['key']}  passed={r['passed']}  B1={r['cheat_summary']}")
        for s in spans:
            attrs = {
                k: s[k]
                for k in ("framing", "strength", "names_benchmark", "status")
                if k in s
            }
            i, j = pos[s["ids"][0]], pos[s["ids"][-1]]
            before = items[i - 1].text if i > 0 else ""
            after = items[j + 1].text if j + 1 < len(items) else ""
            print(f"  [{s['label']}] {s['start']}-{s['end']} {attrs}")
            print(f"      before: {before[: args.width]!r}")
            print(f"      SPAN:   {s['text'][: args.width * 2]!r}")
            print(f"      after:  {after[: args.width]!r}")


if __name__ == "__main__":
    main()
