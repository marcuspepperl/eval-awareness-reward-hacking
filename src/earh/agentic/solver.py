"""Agentic solver: tools until the model stops, with optional CoT prefill on the first call."""

from __future__ import annotations

from typing import Any

from inspect_ai.model import ChatMessageSystem
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash, python, text_editor

from earh.agentic.prompt import SYSTEM_PROMPT, write_task_files
from earh.inspect_provider import generate_with_prefill

TOOL_TIMEOUT_S = 60


@solver
def agentic_agent(max_turns: int = 30, max_parse_errors: int = 3) -> Solver:
    """Tool-using coding agent that works until it stops calling tools.

    Setup writes func.py/test.py and a system prompt. Each turn is one model call
    followed by execution of its tool calls (tool_calls="single"). The first call is
    prefilled with metadata["prefill"] if present; with tools, V4 keeps that reasoning
    in context for the rest of the episode. Malformed tool calls come back to the model
    as tool errors; the episode ends after max_parse_errors of them.

    Writes metadata["agent"] = {stop_reason, turns, tool_calls, parse_errors}, where
    stop_reason is "model_stopped" | "max_turns" | "parse_errors" | "limit" (a task-level
    time/message limit ended the episode).

    @param max_turns: Maximum model calls per episode.
    @param max_parse_errors: Malformed tool calls tolerated before ending the episode.
    @returns: An Inspect solver.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await write_task_files(state.metadata)
        state.messages.insert(0, ChatMessageSystem(content=SYSTEM_PROMPT))
        state.tools = [
            bash(timeout=TOOL_TIMEOUT_S),
            python(timeout=TOOL_TIMEOUT_S),
            text_editor(timeout=TOOL_TIMEOUT_S),
        ]
        info: dict[str, Any] = {
            # stays "limit" if a task-level limit (time/messages) cuts the episode short
            "stop_reason": "limit",
            "turns": 0,
            "tool_calls": 0,
            "parse_errors": 0,
        }
        state.metadata["agent"] = info

        for turn in range(max_turns):
            if turn == 0:
                state = await generate_with_prefill(
                    state,
                    generate,
                    state.metadata.get("prefill", ""),
                    tool_calls="single",
                )
            else:
                state = await generate(state, tool_calls="single")
            message = state.output.message
            info["turns"] += 1
            info["tool_calls"] += len(message.tool_calls or [])
            if (message.metadata or {}).get("tool_parse_error"):
                info["parse_errors"] += 1
                if info["parse_errors"] >= max_parse_errors:
                    info["stop_reason"] = "parse_errors"
                    break
                continue
            if not message.tool_calls:
                info["stop_reason"] = "model_stopped"
                break
        else:
            info["stop_reason"] = "max_turns"
        return state

    return solve
