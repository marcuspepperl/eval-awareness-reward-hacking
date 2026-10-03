"""MiMo-V2.6-Flash raw-prompt rendering (official Jinja template) and completion parsing.

The template is vendored unmodified (`vendor/mimo_v26_flash_chat_template.jinja`, from
the public XiaomiMiMo/MiMo-V2.6-Flash-MOPD repo; the -RL repo's differs only by one
whitespace-stripped blank line; the MiMo-V2.6-Flash repo itself is gated). Token counts
of our renders match DeepInfra's chat endpoint exactly, incl. tools, tool round-trips
and reasoning in history. The generation prompt is `<|im_start|>assistant\\n` and the
model opens `<think>` itself, so we append `<think>` + prefill. Tool calls:
`<tool_call><function=NAME><parameter=K>V</parameter>...</function></tool_call>`.
No reasoning-effort setting (thinking is on or off).
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import jinja2
import jinja2.ext
from jinja2.sandbox import ImmutableSandboxedEnvironment

from earh.glm import _decode_value, _tojson

TEMPLATE_PATH = Path(__file__).parent / "vendor" / "mimo_v26_flash_chat_template.jinja"
STOP = ["<|im_end|>", "<|im_start|>", "<|endoftext|>"]
TOOL_CALL_MARKER = "<tool_call>"
_CALL = re.compile(
    r"<tool_call>\s*<function=([^>\s]+)>(.*?)</function>\s*</tool_call>", re.DOTALL
)
_PARAM = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.DOTALL)


@cache
def _template() -> jinja2.Template:
    """Compile the vendored template with transformers' chat-template Jinja settings."""
    env = ImmutableSandboxedEnvironment(
        trim_blocks=True, lstrip_blocks=True, extensions=[jinja2.ext.loopcontrols]
    )
    env.filters["tojson"] = _tojson
    return env.from_string(TEMPLATE_PATH.read_text())


def build_mimo(
    messages: list[dict[str, Any]],
    prefill: str,
    drop_thinking: bool,
    reasoning_effort: str | None,
) -> str:
    """Render MiMo-V2.6-Flash's official template + `<think>` + prefill.

    Tool definitions arrive on the system message (our provider's convention); they are
    moved to the template's top-level `tools` argument, which is how DeepInfra's chat
    endpoint renders them (a separate system message first). Tool-call arguments are
    decoded from JSON strings to dicts, as the template expects. The template keeps all
    reasoning; with drop_thinking, reasoning before the last user message is removed
    (the GLM/DeepSeek rule, so a single-user agentic episode keeps everything).

    @param messages: See earh.models.Message.
    @param prefill: Text to start the reasoning with ("" for none).
    @param drop_thinking: Drop reasoning of assistant turns before the last user message.
    @param reasoning_effort: Must be None (MiMo has no effort setting).
    @returns: Raw prompt string ending inside an open reasoning block.
    @raises ValueError: If a reasoning effort is given.
    """
    if reasoning_effort is not None:
        raise ValueError("MiMo-V2.6-Flash has no reasoning-effort setting")
    last_user = max(
        (i for i, m in enumerate(messages) if m["role"] == "user"), default=-1
    )
    tools = None
    rendered = []
    for i, m in enumerate(messages):
        m = dict(m)
        if m.get("tools"):
            tools = m.pop("tools")
        if drop_thinking and m["role"] == "assistant" and i < last_user:
            m.pop("reasoning_content", None)
        if m.get("tool_calls"):
            m["tool_calls"] = [
                {
                    **tc,
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.loads(tc["function"]["arguments"]),
                    },
                }
                for tc in m["tool_calls"]
            ]
        rendered.append(m)
    prompt = _template().render(
        messages=rendered, tools=tools, add_generation_prompt=True
    )
    return prompt + "<think>" + prefill


def parse_mimo_completion(
    prefill: str,
    continuation: str,
    finished: bool,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Parse a MiMo-V2.6-Flash thinking completion into reasoning, content and tool calls.

    @param prefill: The prefill the prompt ended with (start of the reasoning).
    @param continuation: Raw generated text (stop tokens already stripped by the API).
    @param finished: Unused (no trailing EOS to restore); kept for a uniform signature.
    @param tools: OpenAI-format tool definitions, used to type parameter values.
    @returns: (reasoning, content, tool_calls) with tool_calls in OpenAI format.
    @raises ValueError: If `</think>` is missing or a tool call is malformed.
    """
    text = prefill + continuation
    if "</think>" not in text:
        raise ValueError("missing </think>")
    reasoning, rest = text.split("</think>", 1)
    content, marker, _ = rest.partition(TOOL_CALL_MARKER)
    raw_calls = _CALL.findall(rest)
    if marker and len(raw_calls) != rest.count(TOOL_CALL_MARKER):
        raise ValueError("malformed <tool_call>")
    schemas = {
        t["function"]["name"]: t["function"].get("parameters", {}).get("properties", {})
        for t in (tools or [])
    }
    calls = []
    for name, body in raw_calls:
        props = schemas.get(name, {})
        args = {k: _decode_value(v, props.get(k)) for k, v in _PARAM.findall(body)}
        calls.append(
            {
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        )
    return reasoning.strip(), content.strip(), calls
