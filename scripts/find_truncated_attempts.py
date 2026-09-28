"""List truncated attempts in a run and diagnose repetition loops.

    uv run python scripts/find_truncated_attempts.py logs/10-observational/v4flash/baseline-8att

Writes results/<log_dir minus logs/>/truncated_attempts.csv (committed). Downstream
analysis joins on (task, sample_id, epoch, attempt) to flag or skip these attempts;
the judge can stop reading reasoning at loop_start.
"""

import csv
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from earh.degenerate import diagnose

FIELDS = [
    "task", "sample_id", "epoch", "attempt", "attempts_made", "sample_outcome",
    "output_tokens", "reasoning_chars", "chars_per_token", "kind",
    "tail_compression", "loop_start", "loop_start_rel", "judge_cutoff", "tail",
]  # fmt: skip


def _text(sample, value: str) -> str:
    """Resolve Inspect's attachment:// references to the stored text."""
    if value.startswith("attachment://"):
        return sample.attachments.get(value.split("//", 1)[1], value)
    return value


def find(log_dir: str) -> list[dict]:
    """Return one row per truncated attempt in all logs under log_dir."""
    rows = []
    for info in list_eval_logs(log_dir):
        log = read_eval_log(info)
        for s in log.samples or []:
            md = next(iter(s.scores.values())).metadata
            attempts = s.metadata.get("attempts", [])
            # Successful model calls only: errored calls were retried and are not attempts.
            calls = [
                e
                for e in s.events
                if e.event == "model"
                and e.error is None
                and e.output
                and e.output.usage
            ]
            if len(calls) != len(attempts):
                print(
                    f"warning: {s.id} epoch {s.epoch}: {len(calls)} calls vs {len(attempts)} attempts"
                )
                continue
            for a, call in zip(attempts, calls, strict=True):
                if not a["truncated"]:
                    continue
                reasoning = " ".join(
                    _text(s, c.reasoning)
                    for c in call.output.message.content
                    if c.type == "reasoning"
                )
                tokens = call.output.usage.output_tokens
                d = diagnose(reasoning)
                rows.append(
                    {
                        "task": log.eval.task,
                        "sample_id": s.id,
                        "epoch": s.epoch,
                        "attempt": a["attempt"],
                        "attempts_made": md["attempts_made"],
                        "sample_outcome": md["outcome"],
                        "output_tokens": tokens,
                        "reasoning_chars": len(reasoning),
                        "chars_per_token": round(len(reasoning) / tokens, 2),
                        "kind": d.kind,
                        "tail_compression": d.tail_compression,
                        "loop_start": d.loop_start,
                        "loop_start_rel": d.loop_start_rel,
                        "judge_cutoff": d.judge_cutoff,
                        "tail": reasoning[-60:].replace("\n", " "),
                    }
                )
    return rows


def main(log_dir: str) -> None:
    """Find truncated attempts, print them, and write the CSV under results/."""
    rows = find(log_dir)
    rel = Path(log_dir).resolve().relative_to(Path("logs").resolve())
    out = Path("results") / rel / "truncated_attempts.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(
            f"{r['task']:24s} {r['sample_id']:12s} e{r['epoch']} a{r['attempt']} "
            f"{r['kind']:10s} tail_compr={r['tail_compression']:<6} loop_start_rel={r['loop_start_rel']}"
        )
    print(f"\n{len(rows)} truncated attempts -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: find_truncated_attempts.py <log_dir>")
    main(sys.argv[1])
