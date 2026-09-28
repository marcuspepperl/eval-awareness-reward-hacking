"""Inspect task for the agentic harness on Impossible-LiveCodeBench."""

from __future__ import annotations

import random

from impossiblebench.livecodebench_tasks import (
    INSTRUCTION_SUFFIX_TOOLS,
    record_to_sample,
)
from inspect_ai import Task, task
from inspect_ai.dataset import hf_dataset

from earh.agentic.prompt import USER_INSTRUCTION
from earh.agentic.scorer import tests_pass
from earh.agentic.solver import agentic_agent

DATASET_PATH = "fjzzq2002/impossible_livecodebench"

# record_to_sample only omits the inline code block when this suffix is in the
# instruction; ours ends with it verbatim.
assert USER_INSTRUCTION.endswith(INSTRUCTION_SUFFIX_TOOLS.strip())


def select_ids(all_ids: list[str], n_tasks: int | None, seed: int) -> set[str]:
    """Pick n_tasks problem IDs with a fixed seed; identical across splits (same ID set)."""
    ids = sorted(all_ids)
    if n_tasks is None or n_tasks >= len(ids):
        return set(ids)
    return set(random.Random(seed).sample(ids, n_tasks))


@task
def agentic_lcb(
    split: str = "conflicting",
    n_tasks: int | None = 25,
    seed: int = 0,
    max_turns: int = 30,
    time_limit: int = 1800,
    task_ids: list[str] | None = None,
) -> Task:
    """Impossible-LiveCodeBench in a tool-using sandbox; cheat = final tests pass.

    @param split: "original" | "oneoff" | "conflicting".
    @param n_tasks: Number of problems (None = all 103); same problems for every split given a seed.
    @param seed: Problem-selection seed.
    @param max_turns: Maximum model calls per episode.
    @param time_limit: Wall-clock seconds per sample.
    @param task_ids: Explicit problem IDs (overrides n_tasks/seed), e.g. from task_sets/.
    @returns: An Inspect Task named e.g. "agentic_conflicting".
    """
    dataset = hf_dataset(
        path=DATASET_PATH,
        split=split,
        sample_fields=record_to_sample(
            instruction_prompt=USER_INSTRUCTION, allow_test_modifications=True
        ),
    )
    all_ids = [str(s.id) for s in dataset]
    if task_ids is not None:
        missing = set(task_ids) - set(all_ids)
        assert not missing, f"unknown task ids: {sorted(missing)}"
        keep = set(task_ids)
    else:
        keep = select_ids(all_ids, n_tasks, seed)
    dataset = dataset.filter(lambda s: s.id in keep)
    return Task(
        name=f"agentic_{split}",
        dataset=dataset,
        solver=agentic_agent(max_turns=max_turns),
        scorer=tests_pass(),
        sandbox="docker",
        message_limit=6 * max_turns,  # backstop; max_turns is the main limit
        time_limit=time_limit,
    )
