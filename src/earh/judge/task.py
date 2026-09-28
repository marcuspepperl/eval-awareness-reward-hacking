"""Inspect task that runs the judge over a units file (one Sample per judge unit).

    uv run inspect eval src/earh/judge/task.py@judge -T units=<units.jsonl> \\
        --model deepinfra-raw/glm53flash -M reasoning_effort=low --log-dir <run>/logs

The solver parses and validates each output; on failure it shows the judge its errors
and asks again (up to max_retries). The scorer records validity and the parsed spans.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver

from earh.judge.parse import parse

RETRY_PROMPT = (
    "Your output had these problems:\n{errors}\n\n"
    "Reply again with the complete corrected output only, in the required format."
)
META_KEYS = ("attempt_key", "pass", "chunk", "n_chunks", "taggable_ids", "meta")


def load_units(
    path: str, passes: str | None = None, limit: int | None = None
) -> MemoryDataset:
    """Read judge units (JSONL) into an Inspect dataset.

    @param path: judge_units.jsonl written by scripts/judge/build_units.py.
    @param passes: Optional comma-separated filter, e.g. "A" or "A,B1".
    @param limit: Optional cap on the number of units (after filtering).
    @returns: One Sample per unit; the unit's fields go into sample metadata.
    """
    keep = set(passes.split(",")) if passes else None
    samples = []
    with open(path) as f:
        for line in f:
            u = json.loads(line)
            if keep and u["pass"] not in keep:
                continue
            samples.append(
                Sample(
                    id=u["id"],
                    input=[
                        ChatMessageSystem(content=u["system"]),
                        ChatMessageUser(content=u["user"]),
                    ],
                    metadata={k: u[k] for k in META_KEYS},
                )
            )
            if limit and len(samples) >= limit:
                break
    return MemoryDataset(samples)


@solver
def judge_solver(max_retries: int = 2) -> Solver:
    """Generate, validate, and retry with the validation errors (up to max_retries).

    Writes metadata["judge"] = {spans, summary, errors, n_retries, valid}.

    @param max_retries: Extra attempts after the first when validation fails.
    @returns: An Inspect solver.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        md = state.metadata
        for attempt in range(max_retries + 1):
            state = await generate(state)
            result = parse(state.output.completion, md["pass"], md["taggable_ids"])
            if not result.errors or attempt == max_retries:
                break
            errors = "\n".join(f"- {e}" for e in result.errors[:10])
            state.messages.append(
                ChatMessageUser(content=RETRY_PROMPT.format(errors=errors))
            )
        state.metadata["judge"] = {
            "spans": result.spans,
            "summary": result.summary,
            "errors": result.errors,
            "n_retries": attempt,
            "valid": not result.errors,
        }
        return state

    return solve


@scorer(metrics={"valid": [mean()], "n_spans": [mean()], "n_retries": [mean()]})
def judge_scorer():
    """Score = validity, span count, and retries (for monitoring); spans go in metadata."""

    async def score(state: TaskState, target: Target) -> Score:
        j = state.metadata["judge"]
        return Score(
            value={
                "valid": float(j["valid"]),
                "n_spans": float(len(j["spans"])),
                "n_retries": float(j["n_retries"]),
            },
            answer=f"{len(j['spans'])} spans" + ("" if j["valid"] else " (invalid)"),
            metadata=j,
        )

    return score


@task
def judge(
    units: str,
    passes: str | None = None,
    limit: int | None = None,
    max_retries: int = 2,
    max_tokens: int = 16_000,
) -> Task:
    """Judge task over a units file.

    @param units: Path to judge_units.jsonl.
    @param passes: Optional pass filter, e.g. "A".
    @param limit: Optional unit cap (for smoke tests).
    @param max_retries: Retries after a structurally invalid output.
    @param max_tokens: Output cap per judge call (includes the judge's own reasoning).
    @returns: An Inspect Task (temperature 0; set reasoning effort via -M on the model).
    """
    return Task(
        dataset=load_units(units, passes, limit),
        solver=judge_solver(max_retries=max_retries),
        scorer=judge_scorer(),
        config=GenerateConfig(temperature=0, max_tokens=max_tokens),
    )
