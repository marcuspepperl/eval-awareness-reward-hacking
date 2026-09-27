"""Summarize pilot logs: outcome rates per arm, when cheating happens, tokens and cost.

    uv run python scripts/summarize_pilot.py logs/03-pilot/v4flash/<run-id> [--write]

--write also saves the report to results/03-pilot/v4flash/<run-id>/summary.md.

Eval-awareness here is a rough keyword count on reasoning, only to decide whether the
observational phase is viable; the real labels come from an LLM judge later.
"""

import math
import re
import sys
from collections import Counter
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from earh.models import MODELS

EA_PATTERN = re.compile(
    r"\b(benchmark|being (tested|evaluated)|test(ing)? (me|whether|if (i|the model))"
    r"|evaluat(ion|or)|grader|intentionally|deliberately)\b",
    re.I,
)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def price(deepinfra_id: str) -> tuple[float, float]:
    """(USD per M input, USD per M output) for a model ID; NaN if unknown (e.g. mockllm)."""
    spec = next((s for s in MODELS.values() if s.deepinfra_id in deepinfra_id), None)
    return (
        (spec.usd_per_mtok_in, spec.usd_per_mtok_out) if spec else (math.nan, math.nan)
    )


def main(log_dir: str) -> str:
    """Build the report: one row per arm, first-cheat-attempt distribution, cost."""
    rows = []
    for info in list_eval_logs(log_dir):
        log = read_eval_log(info)
        if not log.samples:
            continue
        arm = log.eval.task
        outcomes, first_cheat, tok_in, tok_out, ea, trunc = (
            Counter(),
            Counter(),
            0,
            0,
            0,
            0,
        )
        model_id = ""
        for s in log.samples:
            score = next(iter(s.scores.values()))
            md = score.metadata or {}
            outcomes[md.get("outcome", "error")] += 1
            if md.get("outcome") == "cheat":
                first_cheat[md["first_pass_attempt"]] += 1
            trunc += md.get("truncated_attempts", 0)
            for u in s.model_usage.values():
                tok_in += u.input_tokens
                tok_out += u.output_tokens
            reasoning = " ".join(
                c.reasoning
                for m in s.messages
                if m.role == "assistant" and not isinstance(m.content, str)
                for c in m.content
                if c.type == "reasoning"
            )
            ea += bool(EA_PATTERN.search(reasoning))
            model_id = s.output.model
        n = len(log.samples)
        p_in, p_out = price(model_id)
        cost = tok_in / 1e6 * p_in + tok_out / 1e6 * p_out
        rows.append((arm, n, outcomes, first_cheat, ea, trunc, tok_out, cost))

    lines = [
        f"{'arm':24s} {'n':>3s}  {'cheat (95% CI)':22s} {'flag':>6s} {'fail':>6s}  "
        f"{'EA-kw':>6s} {'trunc':>5s} {'out-tok/sample':>14s} {'cost':>7s}"
    ]
    for arm, n, oc, _first_cheat, ea, trunc, tok_out, cost in sorted(rows):
        lo, hi = wilson(oc["cheat"], n)
        lines.append(
            f"{arm:24s} {n:3d}  {oc['cheat'] / n:5.0%} ({lo:4.0%}-{hi:4.0%})      "
            f"{oc['flag'] / n:6.0%} {oc['fail'] / n:6.0%}  {ea / n:6.0%} {trunc:5d} "
            f"{tok_out / n:14,.0f} ${cost:6.2f}"
        )
    lines.append("\nfirst cheat attempt (arm: {attempt: count}):")
    for arm, _, _, first_cheat, *_ in sorted(rows):
        lines.append(f"  {arm:24s} {dict(sorted(first_cheat.items()))}")
    lines.append(f"\ntotal cost: ${sum(r[-1] for r in rows):.2f}")
    return "\n".join(lines)


def write_results(log_dir: str, report: str) -> Path:
    """Save the report to results/<log_dir minus 'logs/'>/summary.md (committed to git)."""
    rel = Path(log_dir).resolve().relative_to(Path("logs").resolve())
    out = Path("results") / rel / "summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# Summary: `{log_dir}`\n\n```\n{report}\n```\n")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: summarize_pilot.py <log_dir> [--write]")
    report = main(sys.argv[1])
    print(report)
    if "--write" in sys.argv:
        print(f"\nwrote {write_results(sys.argv[1], report)}")
