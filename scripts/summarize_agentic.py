"""Summarize agentic-harness logs: cheat rate per split, how episodes ended, tokens and cost.

    uv run python scripts/summarize_agentic.py logs/31-agentic-pilot/v4flash/<run-id> [--write]

--write also saves the report to results/<same path>/summary.md (committed).
"""

import math
import sys
from collections import Counter
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from earh.models import MODELS


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def price(model_id: str) -> tuple[float, float]:
    """(USD per M input, USD per M output) for a DeepInfra model ID; NaN if unknown."""
    spec = next((s for s in MODELS.values() if s.deepinfra_id in model_id), None)
    return (
        (spec.usd_per_mtok_in, spec.usd_per_mtok_out) if spec else (math.nan, math.nan)
    )


def main(log_dir: str) -> str:
    """Build the report: one row per split, then stop reasons and totals."""
    lines = [
        f"{'model':12s} {'task':22s} {'n':>3s}  {'cheat (95% CI)':20s} {'tests-mod':>9s} "
        f"{'turns':>5s} {'parse-err':>9s} {'in-tok':>8s} {'out-tok':>8s} {'min':>5s} {'$/sample':>9s}"
    ]
    stops: dict[str, Counter] = {}
    total_cost = 0.0
    logs = sorted(
        (read_eval_log(i) for i in list_eval_logs(log_dir)),
        key=lambda lg: (lg.eval.model, lg.eval.task),
    )
    for log in logs:
        if not log.samples:
            continue
        errored = [s for s in log.samples if not s.scores]
        samples = [s for s in log.samples if s.scores]
        n = len(samples)
        if n == 0:
            continue
        cheat = mod = turns = perr = tin = tout = 0
        minutes = 0.0
        stop = Counter()
        model_id = ""
        for s in samples:
            score = next(iter(s.scores.values()))
            md = score.metadata or {}
            cheat += int(score.value["cheat"])
            mod += int(score.value["test_modified"])
            turns += md.get("turns") or 0
            perr += md.get("parse_errors") or 0
            stop[md.get("stop_reason", "error")] += 1
            for u in s.model_usage.values():
                tin += u.input_tokens
                tout += u.output_tokens
            minutes += (s.total_time or 0) / 60
            model_id = s.output.model or model_id
        p_in, p_out = price(model_id)
        cost = tin / 1e6 * p_in + tout / 1e6 * p_out
        total_cost += cost
        lo, hi = wilson(cheat, n)
        model_name = log.eval.model.split("/")[-1]
        lines.append(
            f"{model_name:12s} {log.eval.task:22s} {n:3d}  {cheat / n:4.0%} ({lo:4.0%}-{hi:4.0%})     "
            f"{mod / n:9.0%} {turns / n:5.1f} {perr:9d} {tin / n:8,.0f} {tout / n:8,.0f} "
            f"{minutes / n:5.1f} ${cost / n:8.4f}"
        )
        if errored:
            stop["errored (excluded)"] = len(errored)
        stops[f"{model_name} {log.eval.task}"] = stop
    lines.append("\nstop reasons:")
    for task, stop in stops.items():
        lines.append(f"  {task:35s} {dict(stop)}")
    lines.append(f"\ntotal cost: ${total_cost:.2f}")
    return "\n".join(lines)


def write_results(log_dir: str, report: str) -> Path:
    """Save the report to results/<log_dir minus 'logs/'>/summary.md (committed to git)."""
    rel = Path(log_dir).absolute().relative_to(Path("logs").absolute())
    out = Path("results") / rel / "summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# Summary: `{log_dir}`\n\n```\n{report}\n```\n")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: summarize_agentic.py <log_dir> [--write]")
    report = main(sys.argv[1])
    print(report)
    if "--write" in sys.argv:
        print(f"\nwrote {write_results(sys.argv[1], report)}")
