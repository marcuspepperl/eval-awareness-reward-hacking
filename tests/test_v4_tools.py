"""Free unit tests for V4 tool calling (no API calls): encoder goldens, provider conversion, parsing."""

import json
from pathlib import Path

import pytest
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    ContentReasoning,
    ContentText,
)
from inspect_ai.tool import ToolCall, ToolInfo, ToolParam, ToolParams

from earh.inspect_provider import (
    _parse_with_tools,
    _to_messages,
    generate_with_prefill,
    is_prefill,
)
from earh.models import MODELS, build_prompt
from earh.vendor import encoding_dsv4 as E

FIXTURES = Path(__file__).parent / "fixtures" / "dsv4"
V4 = MODELS["v4flash"]
BASH = ToolInfo(
    name="bash",
    description="Run a shell command.",
    parameters=ToolParams(
        properties={"cmd": ToolParam(type="string", description="Command to run")},
        required=["cmd"],
    ),
)


def _load(name: str):
    """Read a golden fixture file."""
    return (FIXTURES / name).read_text()


# --- DeepSeek's own golden cases (guards the vendored encoder) ---------------


def test_golden_case1_tools_thinking():
    """Tools + thinking: encode matches DeepSeek's reference output."""
    td = json.loads(_load("test_input_1.json"))
    messages = td["messages"]
    messages[0]["tools"] = td["tools"]
    assert E.encode_messages(messages, thinking_mode="thinking") == _load(
        "test_output_1.txt"
    )


@pytest.mark.parametrize("case", [2, 3])
def test_golden_thinking_cases(case):
    """Thinking without tools (2) and interleaved thinking + tools (3) match references."""
    messages = json.loads(_load(f"test_input_{case}.json"))
    assert E.encode_messages(messages, thinking_mode="thinking") == _load(
        f"test_output_{case}.txt"
    )


# --- Provider conversion: Inspect messages -> V4 raw prompt ---------------------


def _conversation():
    """A small Inspect conversation with one completed tool call."""
    return [
        ChatMessageSystem(content="You are a coding agent."),
        ChatMessageUser(content="List the files."),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="I should run ls first."),
                ContentText(text=""),
            ],
            tool_calls=[ToolCall(id="c1", function="bash", arguments={"cmd": "ls"})],
        ),
        ChatMessageTool(content="func.py\ntest.py", tool_call_id="c1", function="bash"),
    ]


def test_prompt_with_tools_keeps_history_and_prefill():
    """Tools block, prior tool call, tool result and prior reasoning all render; prefill ends it."""
    prompt = build_prompt(
        V4, _to_messages(_conversation(), [BASH]), "I am probably being tested."
    )
    assert "## Tools" in prompt and '"name": "bash"' in prompt
    assert '<｜DSML｜invoke name="bash">' in prompt
    assert "<tool_result>func.py\ntest.py</tool_result>" in prompt
    assert "I should run ls first." in prompt  # reasoning kept with tools
    assert prompt.endswith("<｜Assistant｜><think>I am probably being tested.")


def test_tool_error_is_rendered():
    """A tool error reaches the model as text in the tool result."""
    from inspect_ai.tool import ToolCallError

    msgs = _conversation()
    msgs[-1] = ChatMessageTool(
        content="",
        tool_call_id="c1",
        function="bash",
        error=ToolCallError(type="timeout", message="Command timed out"),
    )
    prompt = build_prompt(V4, _to_messages(msgs, [BASH]))
    assert "Error: Command timed out" in prompt


def test_no_tools_path_unchanged():
    """Without tools (Track A), tool messages are rejected and no tools block appears."""
    with pytest.raises(ValueError):
        _to_messages(_conversation(), None)
    prompt = build_prompt(V4, _to_messages(_conversation()[:2]))
    assert "## Tools" not in prompt


def test_qwen_rejects_tools():
    """Qwen3's builder has no tool format and must refuse tools."""
    with pytest.raises(ValueError):
        build_prompt(MODELS["qwen3-32b"], _to_messages(_conversation(), [BASH]))


# --- Parsing model output ------------------------------------------------------


def _assistant_span(reasoning: str, content: str, calls: list[dict]) -> str:
    """Render one assistant turn with the real encoder and return what the model would emit."""
    msgs = [
        {"role": "user", "content": "x"},
        {
            "role": "assistant",
            "reasoning_content": reasoning,
            "content": content,
            "tool_calls": calls or None,
        },
    ]
    prompt = E.encode_messages(msgs, thinking_mode="thinking", drop_thinking=False)
    start = prompt.rfind("<｜Assistant｜><think>") + len("<｜Assistant｜><think>")
    return prompt[start:].removesuffix(E.eos_token)


def test_parse_tool_call():
    """A well-formed DSML tool call becomes an Inspect ToolCall with parsed arguments."""
    text = _assistant_span(
        "Run the tests.",
        "",
        [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": json.dumps({"cmd": "python test.py"}),
                },
            }
        ],
    )
    reasoning, answer, calls, err = _parse_with_tools("", text, "stop")
    assert err is None and reasoning == "Run the tests." and answer == ""
    assert len(calls) == 1
    assert calls[0].function == "bash"
    assert calls[0].arguments == {"cmd": "python test.py"}


def test_parse_final_answer_and_prefill():
    """No tool call = final answer; the prefill is the start of the reasoning."""
    text = _assistant_span("rest of thought.", "Done: implemented func.py.", [])
    reasoning, answer, calls, err = _parse_with_tools("Maybe a test. ", text, "stop")
    assert calls == [] and err is None
    assert reasoning.startswith("Maybe a test.") and answer.startswith("Done")


def test_parse_malformed_tool_call():
    """Broken DSML yields one placeholder call with parse_error (loop continues)."""
    text = "thinking</think>\n\n<｜DSML｜tool_calls>\n<｜DSML｜invoke oops"
    reasoning, _, calls, err = _parse_with_tools("", text, "stop")
    assert err and reasoning == "thinking"
    assert len(calls) == 1 and calls[0].parse_error


def test_parse_truncated():
    """Output cut off before </think> is all reasoning, with no calls."""
    reasoning, answer, calls, err = _parse_with_tools(
        "pre ", "still thinking", "length"
    )
    assert reasoning == "pre still thinking" and answer == "" and calls == []
    assert err is None


# --- Prefill helper with tool results -------------------------------------------


async def test_generate_with_prefill_removes_marker_after_tools():
    """The marker is removed by identity even when tool results follow the reply."""

    class State:
        messages: list = []

    async def fake_generate(state, **kwargs):
        assert kwargs == {"tool_calls": "single"}
        assert is_prefill(state.messages[-1])
        state.messages += [
            ChatMessageAssistant(content="reply"),
            ChatMessageTool(content="out", tool_call_id="c1", function="bash"),
        ]
        return state

    state = State()
    state.messages = [ChatMessageUser(content="go")]
    state = await generate_with_prefill(
        state, fake_generate, "prefill", tool_calls="single"
    )
    assert [m.role for m in state.messages] == ["user", "assistant", "tool"]
    assert not any(is_prefill(m) for m in state.messages)
