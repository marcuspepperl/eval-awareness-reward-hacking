"""Inspect task for the agentic harness on Impossible-LiveCodeBench."""

from __future__ import annotations

import random
from typing import Any

from impossiblebench.livecodebench_tasks import record_to_sample
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample, hf_dataset

from earh.agentic.prompt import DEFAULT_PROMPT, user_message
from earh.agentic.scorer import tests_pass
from earh.agentic.solver import agentic_agent

DATASET_PATH = "fjzzq2002/impossible_livecodebench"


def select_ids(all_ids: list[str], n_tasks: int | None, seed: int) -> set[str]:
    """Pick n_tasks problem IDs with a fixed seed; identical across splits (same ID set)."""
    ids = sorted(all_ids)
    if n_tasks is None or n_tasks >= len(ids):
        return set(ids)
    return set(random.Random(seed).sample(ids, n_tasks))


def _sample_fields(user_instruction: str):
    """ImpossibleBench's record_to_sample (metadata), with input = our instruction only.

    Their converter inlines the signature + tests into the input unless the instruction
    contains their tools-scaffold suffix; the files carry that content here, so we replace
    the input with the bare instruction.
    """
    convert = record_to_sample(
        instruction_prompt=user_instruction, allow_test_modifications=True
    )

    def fields(record: dict[str, Any]) -> Sample:
        sample = convert(record)
        sample.input = user_instruction
        return sample

    return fields


@task
def agentic_lcb(
    split: str = "conflicting",
    n_tasks: int | None = 25,
    seed: int = 0,
    max_turns: int = 60,
    time_limit: int = 3600,
    task_ids: list[str] | None = None,
    prompt_version: str = DEFAULT_PROMPT,
    exit: str | None = None,
    pressure: str = "none",
    tool_budget: int | None = None,
    budget_warn_at: int = 5,
) -> Task:
    """Impossible-LiveCodeBench in a tool-using sandbox; cheat = final tests pass.

    @param split: "original" | "oneoff" | "conflicting".
    @param n_tasks: Number of problems (None = all 103); same problems for every split given a seed.
    @param seed: Problem-selection seed.
    @param max_turns: Maximum model calls per episode.
    @param time_limit: Wall-clock seconds per sample.
    @param task_ids: Explicit problem IDs (overrides n_tasks/seed), e.g. from task_sets/.
    @param prompt_version: "v2" (default, minimal) or "v1" (legacy); see earh.agentic.prompt.
    @param exit: Optional exit tool, "end_task" (neutral) or "give_up" (sanctions failure).
    @param pressure: "none" | "mild" | "strong": deadline/stakes text appended to the user
        message (see earh.agentic.prompt.PRESSURE).
    @param tool_budget: Optional visible tool-call budget with a countdown in tool results
        (see agentic_agent); None = no budget.
    @param budget_warn_at: Remaining calls at or below which the countdown becomes the
        end-of-session warning (0 = never).
    @returns: An Inspect Task named e.g. "agentic_conflicting".
    """
    user_instruction = user_message(prompt_version, pressure)
    dataset = hf_dataset(
        path=DATASET_PATH, split=split, sample_fields=_sample_fields(user_instruction)
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
        name=f"agentic_{split}"
        + (f"_{exit}" if exit else "")
        + (f"_pressure-{pressure}" if pressure != "none" else "")
        + (f"_budget-{tool_budget}" if tool_budget is not None else ""),
        dataset=dataset,
        solver=agentic_agent(
            max_turns=max_turns,
            prompt_version=prompt_version,
            exit=exit,
            tool_budget=tool_budget,
            budget_warn_at=budget_warn_at,
        ),
        scorer=tests_pass(),
        sandbox="docker",
        message_limit=6 * max_turns,  # backstop; max_turns is the main limit
        time_limit=time_limit,
        metadata={
            "prompt_version": prompt_version,
            "exit": exit,
            "pressure": pressure,
            "tool_budget": tool_budget,
            "budget_warn_at": budget_warn_at,
        },
    )


@task
def agentic_lcb_batches(
    batches: list[str] | None = None,
    task_ids: list[str] | None = None,
    max_turns: int = 60,
    time_limit: int = 3600,
    prompt_version: str = DEFAULT_PROMPT,
) -> Task:
    """Several (split, sample) batches as one ordered dataset, sharing one sample queue.

    Inspect starts samples in dataset order as concurrency slots free up, so earlier
    batches start first, but no batch waits for another to finish. Sample IDs get a
    batch suffix (e.g. "lcbhard_12-c1" = conflicting, sample 1); metadata["batch"] holds
    the batch name. The solver and scorer read each sample's own files/tests from its
    metadata, so splits can be mixed. Baseline condition only (no exit tool, pressure,
    budget).

    @param batches: Ordered "split-k" names, e.g. ["conflicting-1", "oneoff-2"]
        (default: those two plus "conflicting-2"); k only labels the repeat.
    @param task_ids: Problem IDs to include (default: all 103).
    @param max_turns: Maximum model calls per episode.
    @param time_limit: Wall-clock seconds per sample.
    @param prompt_version: "v2" (default) or "v1"; see earh.agentic.prompt.
    @returns: An Inspect Task named "agentic_batches".
    """
    batches = batches or ["conflicting-1", "oneoff-2", "conflicting-2"]
    user_instruction = user_message(prompt_version, "none")
    by_split: dict[str, list[Sample]] = {}
    samples: list[Sample] = []
    for batch in batches:
        split, _, k = batch.rpartition("-")
        if split not in by_split:
            ds = hf_dataset(
                path=DATASET_PATH,
                split=split,
                sample_fields=_sample_fields(user_instruction),
            )
            by_split[split] = [s for s in ds if task_ids is None or s.id in task_ids]
        for s in by_split[split]:
            samples.append(
                s.model_copy(
                    update={
                        "id": f"{s.id}-{split[0]}{k}",
                        "metadata": {**(s.metadata or {}), "batch": batch},
                    },
                    deep=True,
                )
            )
    return Task(
        name="agentic_batches",
        dataset=MemoryDataset(samples, name="+".join(batches)),
        solver=agentic_agent(max_turns=max_turns, prompt_version=prompt_version),
        scorer=tests_pass(),
        sandbox="docker",
        message_limit=6 * max_turns,
        time_limit=time_limit,
        metadata={"prompt_version": prompt_version, "batches": batches},
    )
