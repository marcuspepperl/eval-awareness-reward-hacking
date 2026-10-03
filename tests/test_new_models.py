"""Free unit tests for DeepSeek-V4.1-Flash and GLM-5.3-Flash support (no API calls)."""

import json
from pathlib import Path

import pytest

from earh.inspect_provider import _parse_with_tools
from earh.models import MODELS, build_prompt
from earh.vendor import encoding_dsv41 as E41

FIX = Path(__file__).parent / "fixtures"
V41, GLM = MODELS["v41flash"], MODELS["glm53flash"]


# --- DeepSeek-V4.1 ----------------------------------------------------------------


@pytest.mark.parametrize("case_id", [1, 2, 3, 4, 5])
def test_v41_golden(case_id):
    """The vendored V4.1 encoder reproduces DeepSeek's golden outputs."""
    case = E41.load_cases(str(FIX / "dsv41" / f"test_input_{case_id}.json"))[0]
    prompt, _ = E41.encode_case(case, thinking_mode="chat")
    assert prompt == (FIX / "dsv41" / f"test_output_{case_id}.txt").read_text()


def test_v41_tool_roundtrip_through_our_parser():
    """A V4.1 (spaced-DSML) tool call rendered by the encoder parses back via ModelSpec.parse."""
    call = {
        "type": "function",
        "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})},
    }
    msgs = [
        {"role": "user", "content": "x"},
        {
            "role": "assistant",
            "reasoning_content": "List files.",
            "content": "",
            "tool_calls": [call],
        },
    ]
    prompt = E41.encode_messages(msgs, thinking_mode="thinking", drop_thinking=False)
    start = prompt.rfind("<｜Assistant｜><think>") + len("<｜Assistant｜><think>")
    text = prompt[start:].removesuffix(E41.eos_token)
    assert "<｜DSML｜ calls>" in text  # V4.1's spaced tags, unlike V4
    reasoning, answer, calls, err = _parse_with_tools(V41, "", text, "stop")
    assert err is None and reasoning == "List files." and answer == ""
    assert calls[0].function == "bash" and calls[0].arguments == {"command": "ls"}


def test_v41_prompt_ends_in_open_reasoning_with_prefill():
    """build_prompt ends inside <think> + prefill, with V4.1's default effort prefix."""
    prompt = build_prompt(V41, [{"role": "user", "content": "hi"}], "Hmm, a test?")
    assert prompt.endswith("<｜Assistant｜><think>Hmm, a test?")
    assert "Reasoning Effort: 75" in prompt


# --- GLM-5.3 -------------------------------------------------------------------------


def _glm_case():
    """Oracle conversation, reshaped into our provider's convention (tools on system msg, JSON args)."""
    case = json.loads((FIX / "glm53" / "conversation.json").read_text())
    messages = []
    for m in case["messages"]:
        m = dict(m)
        if m.get("tool_calls"):
            m["tool_calls"] = [
                {
                    **tc,
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.dumps(tc["function"]["arguments"]),
                    },
                }
                for tc in m["tool_calls"]
            ]
        messages.append(m)
    messages[0]["tools"] = case["tools"]
    return case, messages


def test_glm_render_matches_transformers_oracle():
    """Our Jinja setup renders the official template exactly as transformers does."""
    _, messages = _glm_case()
    expected = (FIX / "glm53" / "conversation_expected.txt").read_text()
    assert build_prompt(GLM, messages) == expected


def test_glm_prefill_and_history_reasoning():
    """Prompt ends with <|assistant|><think> + prefill; prior reasoning is kept."""
    _, messages = _glm_case()
    prompt = build_prompt(GLM, messages, "Maybe I'm being tested.")
    assert prompt.endswith("<|assistant|><think>Maybe I'm being tested.")
    assert "<think>Look at the files first.</think>" in prompt


def test_glm_parse_tool_call_with_typed_args():
    """String params stay raw; non-string params are JSON-decoded (template's encoding rule)."""
    case, _ = _glm_case()
    text = (
        "I'll view the file.</think>"
        "<tool_call>text_editor<arg_key>command</arg_key><arg_value>view</arg_value>"
        "<arg_key>path</arg_key><arg_value>func.py</arg_value>"
        "<arg_key>view_range</arg_key><arg_value>[1, 5]</arg_value></tool_call>"
    )
    reasoning, answer, calls, err = _parse_with_tools(
        GLM, "", text, "stop", case["tools"]
    )
    assert err is None and reasoning == "I'll view the file." and answer == ""
    assert calls[0].function == "text_editor"
    assert calls[0].arguments == {
        "command": "view",
        "path": "func.py",
        "view_range": [1, 5],
    }


def test_glm_parse_final_answer_malformed_and_truncated():
    """Final answer -> no calls; unterminated call -> placeholder; truncation -> all reasoning."""
    r, a, calls, err = _parse_with_tools(GLM, "pre ", "done.</think>All good.", "stop")
    assert (r, a, calls, err) == ("pre done.", "All good.", [], None)
    _, _, calls, err = _parse_with_tools(
        GLM, "", "x</think><tool_call>bash<arg_key>command", "stop"
    )
    assert err and len(calls) == 1 and calls[0].parse_error
    r, a, calls, err = _parse_with_tools(GLM, "", "still thinking", "length")
    assert r == "still thinking" and a == "" and calls == [] and err is None


# --- MiMo-V2.6-Flash -------------------------------------------------------------------

MIMO = MODELS["mimo26flash"]


def _mimo_case():
    """Golden conversation (token counts checked against DeepInfra's chat endpoint), in our provider's convention."""
    case = json.loads((FIX / "mimo26" / "conversation.json").read_text())
    messages = [dict(m) for m in case["messages"]]
    messages[0]["tools"] = case["tools"]
    return case, messages


def test_mimo_render_matches_golden():
    """build_prompt renders the vendored template as checked against DeepInfra, + <think>."""
    _, messages = _mimo_case()
    expected = (FIX / "mimo26" / "conversation_expected.txt").read_text()
    assert build_prompt(MIMO, messages) == expected + "<think>"


def test_mimo_prefill_and_history_reasoning():
    """Prompt ends with assistant\\n<think> + prefill; reasoning in history is kept."""
    _, messages = _mimo_case()
    prompt = build_prompt(MIMO, messages, "Maybe I'm being tested.")
    assert prompt.endswith("<|im_start|>assistant\n<think>Maybe I'm being tested.")
    assert "<think>Look at the file first.</think>" in prompt


def test_mimo_parse_tool_call_with_typed_args():
    """String params stay raw; non-string params are JSON-decoded."""
    case, _ = _mimo_case()
    text = (
        "I'll view the file.</think>"
        "<tool_call><function=text_editor><parameter=command>view</parameter>"
        "<parameter=path>func.py</parameter><parameter=view_range>[1, 5]</parameter>"
        "</function></tool_call>"
    )
    reasoning, answer, calls, err = _parse_with_tools(
        MIMO, "", text, "stop", case["tools"]
    )
    assert err is None and reasoning == "I'll view the file." and answer == ""
    assert calls[0].function == "text_editor"
    assert calls[0].arguments == {
        "command": "view",
        "path": "func.py",
        "view_range": [1, 5],
    }


def test_mimo_parse_final_answer_malformed_and_truncated():
    """Final answer -> no calls; unterminated call -> placeholder; truncation -> all reasoning."""
    r, a, calls, err = _parse_with_tools(MIMO, "pre ", "done.</think>All good.", "stop")
    assert (r, a, calls, err) == ("pre done.", "All good.", [], None)
    _, _, calls, err = _parse_with_tools(
        MIMO, "", "x</think><tool_call><function=bash><parameter=command>ls", "stop"
    )
    assert err and len(calls) == 1 and calls[0].parse_error
    r, a, calls, err = _parse_with_tools(MIMO, "", "still thinking", "length")
    assert r == "still thinking" and a == "" and calls == [] and err is None
