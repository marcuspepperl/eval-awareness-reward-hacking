"""Assemble judge logs into per-attempt judgments (JSONL).

uv run python scripts/judge/assemble.py logs/12-judge/pilot-smoke
"""

import json
import sys
from pathlib import Path

from earh.judge.assemble import assemble, load_judge_spans
from earh.judge.extract import Attempt


def main(run_dir: str) -> None:
    """Read <run_dir>/attempts.jsonl + judge logs in <run_dir>/logs; write judgments.jsonl."""
    run = Path(run_dir)
    attempts = [Attempt(**json.loads(line)) for line in (run / "attempts.jsonl").open()]
    records = assemble(attempts, load_judge_spans(str(run / "logs")))
    with (run / "judgments.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    n_ea = sum(r["ea_occurrences"] > 0 for r in records)
    n_bad = sum(bool(r["invalid_units"]) for r in records)
    print(
        f"{len(records)} attempts judged; {n_ea} with EA; {n_bad} with invalid units -> {run}/judgments.jsonl"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: assemble.py <run_dir>")
    main(sys.argv[1])
