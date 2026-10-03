"""Agentic solver: tools until the model stops, with optional CoT prefill on the first call."""

from __future__ import annotations

from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ContentText,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import ToolCallError, bash, python, text_editor

from earh.agentic.exit_tools import exit_tool
from earh.agentic.prompt import (
    BUDGET_COUNTER,
    BUDGET_EXHAUSTED,
    BUDGET_LOW,
    BUDGET_REJECTED,
    BUDGET_SYSTEM,
    DEFAULT_PROMPT,
    PROMPTS,
    write_task_files,
)
from earh.inspect_provider import generate_with_prefill

TOOL_TIMEOUT_S = 60


def _append_note(new_messages: list[ChatMessage], note: str) -> None:
    """Append a harness note to the end of this turn's last tool result (after any error)."""
    tools = [m for m in new_messages if m.role == "tool"]
    if not tools:
        return
    last = tools[-1]
    if last.error:  # rendered after the content, so the note goes on the error
        last.error = ToolCallError(last.error.type, f"{last.error.message}\n\n{note}")
    elif isinstance(last.content, str):
        last.content = f"{last.content}\n\n{note}"
    else:
        last.content = [*last.content, ContentText(text=f"\n\n{note}")]


@solver
def agentic_agent(
    max_turns: int = 60,
    max_parse_errors: int = 3,
    max_truncation_retries: int = 2,
    prompt_version: str = DEFAULT_PROMPT,
    exit: str | None = None,
    tool_budget: int | None = None,
    budget_warn_at: int = 0,
    budget_grace: int = 0,
) -> Solver:
    """Tool-using coding agent that works until it stops calling tools.

    Setup writes func.py/test.py and the system prompt. Each turn is one model call
    followed by execution of its tool calls (tool_calls="single"). The first call is
    prefilled with metadata["prefill"] if present; with tools, prior reasoning stays in
    context for the rest of the episode.

    Infrastructure limits are never read as the model's choice:
    - A call cut off by max_tokens is discarded and resampled (up to
      max_truncation_retries); if it keeps truncating, the episode ends as "truncated".
    - A call rejected for exceeding the context window ends the episode as
      "context_overflow".
    - Malformed tool calls come back to the model as tool errors; the episode ends
      after max_parse_errors of them.

    Writes metadata["agent"] = {stop_reason, turns, tool_calls, parse_errors,
    truncations}. stop_reason is "model_stopped" | "max_turns" | "parse_errors" |
    "truncated" | "context_overflow" | "end_task" | "give_up" | "budget_exhausted" |
    "limit" (a task-level time/message limit ended the episode).

    With tool_budget, the system prompt states the budget, every tool result ends with
    the number of calls remaining (with a "save your changes" reminder once at most
    budget_warn_at remain), and once it is used up tools are no longer executed:
    answering ends the episode as "model_stopped". A tool call made anyway gets a
    "not executed" result, up to budget_grace times; the next one ends the episode as
    "budget_exhausted".

    @param max_turns: Maximum (kept) model calls per episode.
    @param max_parse_errors: Malformed tool calls tolerated before ending the episode.
    @param max_truncation_retries: Resamples allowed for a single truncated call.
    @param prompt_version: Key into earh.agentic.prompt.PROMPTS (system prompt used here).
    @param exit: Optional exit tool, "end_task" or "give_up" (see exit_tools); calling it
        ends the episode with stop_reason = its name.
    @param tool_budget: Optional visible budget of tool calls (see above).
    @param budget_warn_at: Remaining-call count at or below which the counter adds the
        save reminder (0 = never).
    @param budget_grace: Rejected tool calls tolerated after the budget is exhausted.
    @returns: An Inspect solver.
    """
    system_prompt = PROMPTS[prompt_version][0]
    if tool_budget is not None:
        system_prompt += "\n\n" + BUDGET_SYSTEM.format(n=tool_budget)

    async def call(
        state: TaskState, generate: Generate, first: bool, execute: bool
    ) -> TaskState:
        """One model call + tool execution (unless execute=False); the first call carries the prefill."""
        tool_calls = "single" if execute else "none"
        if first:
            prefill = state.metadata.get("prefill", "")
            return await generate_with_prefill(
                state, generate, prefill, tool_calls=tool_calls
            )
        return await generate(state, tool_calls=tool_calls)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await write_task_files(state.metadata)
        state.messages.insert(0, ChatMessageSystem(content=system_prompt))
        state.tools = [
            bash(timeout=TOOL_TIMEOUT_S),
            python(timeout=TOOL_TIMEOUT_S),
            text_editor(timeout=TOOL_TIMEOUT_S),
        ] + ([exit_tool(exit)] if exit else [])
        info: dict[str, Any] = {
            # stays "limit" if a task-level limit (time/messages) cuts the episode short
            "stop_reason": "limit",
            "turns": 0,
            "tool_calls": 0,
            "parse_errors": 0,
            "truncations": 0,
            "rejected_calls": 0,
        }
        state.metadata["agent"] = info

        for turn in range(max_turns):
            final = tool_budget is not None and info["tool_calls"] >= tool_budget
            for _attempt in range(max_truncation_retries + 1):
                n_before = len(state.messages)
                state = await call(state, generate, first=turn == 0, execute=not final)
                if state.output.stop_reason != "max_tokens":
                    break
                # Truncated (no tool call, reasoning cut mid-thought): discard and resample.
                info["truncations"] += 1
                del state.messages[n_before:]
            message = state.output.message
            if state.output.stop_reason == "max_tokens":
                info["stop_reason"] = "truncated"
                break
            if state.output.stop_reason == "model_length":
                info["stop_reason"] = "context_overflow"
                break
            info["turns"] += 1
            if final:
                if not message.tool_calls:
                    info["stop_reason"] = "model_stopped"
                    break
                if info["rejected_calls"] >= budget_grace:
                    info["stop_reason"] = "budget_exhausted"
                    break
                info["rejected_calls"] += 1
                state.messages.extend(
                    ChatMessageTool(
                        content=BUDGET_REJECTED,
                        tool_call_id=tc.id,
                        function=tc.function,
                    )
                    for tc in message.tool_calls
                )
                continue
            info["tool_calls"] += len(message.tool_calls or [])
            if tool_budget is not None:
                remaining = tool_budget - info["tool_calls"]
                if remaining <= 0:
                    note = BUDGET_EXHAUSTED
                elif remaining <= budget_warn_at:
                    note = BUDGET_LOW.format(n=remaining)
                else:
                    note = BUDGET_COUNTER.format(n=remaining)
                _append_note(state.messages[n_before:], note)
            if (message.metadata or {}).get("tool_parse_error"):
                info["parse_errors"] += 1
                if info["parse_errors"] >= max_parse_errors:
                    info["stop_reason"] = "parse_errors"
                    break
                continue
            if not message.tool_calls:
                info["stop_reason"] = "model_stopped"
                break
            if exit and any(tc.function == exit for tc in message.tool_calls):
                info["stop_reason"] = exit
                break
        else:
            info["stop_reason"] = "max_turns"
        return state

    return solve
