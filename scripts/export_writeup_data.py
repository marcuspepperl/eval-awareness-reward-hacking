"""Export small JSON files for the writeup's charts from Inspect logs.

    uv run python scripts/export_writeup_data.py logs/10-observational/v4flash/baseline-8att

Writes site/data/phase1_by_task.json and site/data/phase1_by_attempt.json. Only
aggregates go to the site (never raw logs), so every number in the writeup can be
regenerated with this script.
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

OUT = Path("site/data")
BOOTSTRAP = 2_000


def load(log_dir: str) -> list[dict]:
    """One row per sample: split, task id, epoch, outcome, first passing attempt."""
    rows = []
    for info in list_eval_logs(log_dir):
        log = read_eval_log(info)
        for s in log.samples or []:
            if s.error or not s.scores:
                continue
            md = next(iter(s.scores.values())).metadata
            rows.append(
                {
                    "split": s.metadata["impossible_type"],
                    "task": str(s.id),
                    "epoch": s.epoch,
                    "cheat": md["outcome"] == "cheat",
                    "first_pass": md["first_pass_attempt"],
                    "max_attempts": len(s.metadata.get("attempts", [])),
                }
            )
    return rows


def by_task(rows: list[dict]) -> list[dict]:
    """Cheat count per (split, task)."""
    acc: dict[tuple, list[bool]] = defaultdict(list)
    for r in rows:
        acc[(r["split"], r["task"])].append(r["cheat"])
    return [
        {"split": sp, "task": t, "cheats": sum(v), "n": len(v), "rate": sum(v) / len(v)}
        for (sp, t), v in sorted(acc.items())
    ]


def _cum_rate(tasks: dict[str, list[dict]], ids: list[str], k: int) -> float:
    """Share of the samples of the given task ids that first passed by attempt k."""
    rs = [r for t in ids for r in tasks[t]]
    return sum(r["first_pass"] is not None and r["first_pass"] <= k for r in rs) / len(
        rs
    )


def by_attempt(rows: list[dict], max_k: int = 8, seed: int = 0) -> list[dict]:
    """Cumulative cheat rate by attempt k per split, with a cluster bootstrap CI over tasks."""
    rng = random.Random(seed)
    out = []
    for split in sorted({r["split"] for r in rows}):
        tasks: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            if r["split"] == split:
                tasks[r["task"]].append(r)
        ids = list(tasks)
        boots = [[rng.choice(ids) for _ in ids] for _ in range(BOOTSTRAP)]
        for k in range(1, max_k + 1):
            dist = sorted(_cum_rate(tasks, b, k) for b in boots)
            out.append(
                {
                    "split": split,
                    "attempt": k,
                    "rate": _cum_rate(tasks, ids, k),
                    "lo": dist[int(0.025 * BOOTSTRAP)],
                    "hi": dist[int(0.975 * BOOTSTRAP) - 1],
                    "n_tasks": len(ids),
                }
            )
    return out


def main(log_dir: str) -> None:
    """Read logs, write the chart JSON files, print a one-line summary."""
    rows = load(log_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [
        ("phase1_by_task", by_task(rows)),
        ("phase1_by_attempt", by_attempt(rows)),
    ]:
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1))
    print(f"{len(rows)} samples -> {OUT}/phase1_by_task.json, phase1_by_attempt.json")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: export_writeup_data.py <log_dir>")
    main(sys.argv[1])
