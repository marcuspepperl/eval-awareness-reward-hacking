"""GLM-5.3 raw-prompt rendering (official Jinja template) and completion parsing.

The template is vendored unmodified (`vendor/glm53_chat_template.jinja`) and rendered
with the same Jinja setup Hugging Face transformers uses for chat templates. It ends
the generation prompt with `<|assistant|><think>`, keeps all prior reasoning by
default (clear_thinking=false), and uses its own tool-call format:
`<tool_call>NAME<arg_key>K</arg_key><arg_value>V</arg_value>...</tool_call>`.
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

TEMPLATE_PATH = Path(__file__).parent / "vendor" / "glm53_chat_template.jinja"
STOP = ["<|user|>", "<|observation|>", "<|endoftext|>"]
TOOL_CALL_MARKER = "<tool_call>"
_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_ARG = re.compile(r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>", re.DOTALL)


def _tojson(
    x: Any, ensure_ascii: bool = False, indent=None, separators=None, sort_keys=False
) -> str:
    """Jinja `tojson` filter with the keyword arguments HF chat templates use."""
    return json.dumps(
        x,
        ensure_ascii=ensure_ascii,
        indent=indent,
        separators=separators,
        sort_keys=sort_keys,
    )


@cache
def _template() -> jinja2.Template:
    """Compile the vendored template with transformers' chat-template Jinja settings."""
    env = ImmutableSandboxedEnvironment(
        trim_blocks=True, lstrip_blocks=True, extensions=[jinja2.ext.loopcontrols]
    )
    env.filters["tojson"] = _tojson

    def raise_exception(message: str):
        raise jinja2.exceptions.TemplateError(message)

    env.globals["raise_exception"] = raise_exception
    return env.from_string(TEMPLATE_PATH.read_text())


def build_glm(
    messages: list[dict[str, Any]],
    prefill: str,
    drop_thinking: bool,
    reasoning_effort: str | None,
) -> str:
    """Render GLM-5.3's official template (ends with `<|assistant|><think>`) + prefill.

    Tool definitions arrive on the system message (the V4 convention used by our
    provider); they are moved to the template's `tools` argument. Tool-call arguments
    arrive as JSON strings (OpenAI format) and are decoded to dicts, as the template
    expects.

    @param messages: See earh.models.Message.
    @param prefill: Text to start the reasoning with ("" for none).
    @param drop_thinking: Maps to the template's clear_thinking (default False = keep).
    @param reasoning_effort: "low" | "high" | None (None = the template's default, "max").
    @returns: Raw prompt string ending inside an open reasoning block.
    """
    tools = None
    rendered = []
    for m in messages:
        m = dict(m)
        if m.get("tools"):
            tools = m.pop("tools")
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
    kwargs: dict[str, Any] = {"clear_thinking": drop_thinking}
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    prompt = _template().render(
        messages=rendered, tools=tools, add_generation_prompt=True, **kwargs
    )
    return prompt + prefill


def _decode_value(raw: str, schema: dict[str, Any] | None) -> Any:
    """Decode an <arg_value>: raw text for string params, JSON otherwise (template's rule)."""
    if schema and schema.get("type") == "string":
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_glm_completion(
    prefill: str,
    continuation: str,
    finished: bool,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Parse a GLM-5.3 thinking-mode completion into reasoning, content and tool calls.

    @param prefill: The prefill the prompt ended with (start of the reasoning).
    @param continuation: Raw generated text (stop tokens already stripped by the API).
    @param finished: Unused (GLM output has no trailing EOS to restore); kept for a uniform signature.
    @param tools: OpenAI-format tool definitions, used to type argument values.
    @returns: (reasoning, content, tool_calls) with tool_calls in OpenAI format.
    @raises ValueError: If `</think>` is missing or a tool call is malformed.
    """
    text = prefill + continuation
    if "</think>" not in text:
        raise ValueError("missing </think>")
    reasoning, rest = text.split("</think>", 1)
    content, marker, _ = rest.partition(TOOL_CALL_MARKER)
    raw_calls = _CALL.findall(rest)
    if marker and not raw_calls:
        raise ValueError("unterminated <tool_call>")
    schemas = {
        t["function"]["name"]: t["function"].get("parameters", {}).get("properties", {})
        for t in (tools or [])
    }
    calls = []
    for raw in raw_calls:
        name = raw.split("<arg_key>", 1)[0].strip()
        if not name:
            raise ValueError(f"tool call without a name: {raw[:80]!r}")
        props = schemas.get(name, {})
        args = {
            k.strip(): _decode_value(v, props.get(k.strip()))
            for k, v in _ARG.findall(raw)
        }
        calls.append(
            {
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        )
    return reasoning.strip(), content.strip(), calls
