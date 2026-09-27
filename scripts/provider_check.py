"""End-to-end check of the deepinfra-raw provider through `inspect eval`.

    uv run inspect eval scripts/provider_check.py --model deepinfra-raw/v4flash
    uv run inspect eval scripts/provider_check.py --model deepinfra-raw/qwen3-32b

Three tiny tasks: plain generation, CoT prefill, and a two-turn conversation
(exercises assistant history + drop_thinking). Browse results with `inspect view`.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ContentReasoning
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, generate, solver

from earh.inspect_provider import generate_with_prefill

PREFILL = "Okay, let me read the problem. Hmm, this looks like it might be a benchmark problem, maybe I'm being tested."

DATASET = [
    Sample(input="What is 17 * 23? Answer with just the number.", target="391"),
    Sample(
        input="What is the capital of Australia? Answer with one word.",
        target="Canberra",
    ),
]


@scorer(metrics=[accuracy()])
def format_ok():
    """Pass if reasoning and answer are both non-empty and the answer contains the target."""

    async def score(state: TaskState, target: Target) -> Score:
        msg = state.output.message
        reasoning = "".join(
            c.reasoning for c in msg.content if isinstance(c, ContentReasoning)
        )
        prefills_in_history = sum(
            1 for m in state.messages if (m.metadata or {}).get("cot_prefill")
        )
        checks = {
            "has_reasoning": bool(reasoning.strip()),
            "has_answer": bool(msg.text.strip()),
            "answer_correct": target.text.lower() in msg.text.lower(),
            "no_prefill_msg_left": prefills_in_history == 0,
            "reasoning_starts_with_prefill": reasoning.startswith(PREFILL)
            if state.metadata.get("prefill")
            else True,
        }
        return Score(
            value="C" if all(checks.values()) else "I",
            answer=msg.text[:200],
            metadata=checks,
        )

    return score


@solver
def prefilled():
    """Solver: one generate with PREFILL as the start of the reasoning."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.metadata["prefill"] = True
        return await generate_with_prefill(state, generate, PREFILL)

    return solve


@solver
def two_turns():
    """Solver: generate, add a follow-up user message, generate again."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        state.messages.append(
            ChatMessageUser(content="Are you sure? Reply with the same answer again.")
        )
        return await generate(state)

    return solve


@task
def plain():
    """Task: plain generation."""
    return Task(dataset=DATASET, solver=generate(), scorer=format_ok())


@task
def prefill():
    """Task: prefilled generation."""
    return Task(dataset=DATASET, solver=prefilled(), scorer=format_ok())


@task
def multiturn():
    """Task: two-turn conversation (checks history + drop_thinking)."""
    return Task(dataset=DATASET, solver=two_turns(), scorer=format_ok())
