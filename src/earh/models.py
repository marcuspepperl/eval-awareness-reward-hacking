"""Model registry and raw-prompt rendering for DeepInfra's text-completions endpoint.

We render prompts ourselves (instead of using a chat API) so we can prefill the
model's reasoning block, e.g. inject an eval-awareness sentence mid-CoT.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from earh.vendor import encoding_dsv4

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# {role, content, reasoning_content?, tools?, tool_calls?, tool_call_id?}; tool fields use the
# OpenAI format, which the vendored V4 encoder accepts directly.
Message = dict[str, Any]


def _build_v4(
    messages: list[Message],
    prefill: str,
    drop_thinking: bool,
    reasoning_effort: str | None,
) -> str:
    """Render via DeepSeek's official encoder (which ends with an open `<think>`) + prefill."""
    prompt = encoding_dsv4.encode_messages(
        messages,
        thinking_mode="thinking",
        drop_thinking=drop_thinking,
        reasoning_effort=reasoning_effort,
    )
    return prompt + prefill


def _build_qwen3(
    messages: list[Message],
    prefill: str,
    drop_thinking: bool,
    reasoning_effort: str | None,
) -> str:
    """Render Qwen3's ChatML template, then open `<think>` ourselves.

    Qwen3-32B's official generation prompt stops at `<|im_start|>assistant\\n` and the
    model emits `<think>\\n` itself in thinking mode. We add it so every condition
    (baseline and prefilled) starts from the same prefix, and so a prefill lands
    inside the reasoning block.

    @param messages: [{role, content, reasoning_content?}] in conversation order.
    @param prefill: Text to start the reasoning with ("" for none).
    @param drop_thinking: If True, omit reasoning from prior assistant turns (official behavior).
    @param reasoning_effort: Must be None; Qwen3 has no effort setting.
    @returns: Raw prompt string ending inside an open reasoning block.
    """
    if reasoning_effort is not None:
        raise ValueError("Qwen3 has no reasoning_effort setting")
    if any(
        m.get("tools") or m.get("tool_calls") or m["role"] == "tool" for m in messages
    ):
        raise ValueError("Qwen3 prompt builder does not support tools")
    parts = []
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant":
            reasoning = m.get("reasoning_content", "")
            if reasoning and not drop_thinking:
                content = f"<think>\n{reasoning}\n</think>\n\n{content}"
        parts.append(f"<|im_start|>{m['role']}\n{content}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n<think>\n")
    return "".join(parts) + prefill


@dataclass(frozen=True)
class ModelSpec:
    """Static per-model config: DeepInfra ID, prompt builder, stop tokens, sampling/length defaults, pricing."""

    name: str
    deepinfra_id: str
    build: Callable[[list[Message], str, bool, str | None], str]
    stop: list[str]
    temperature: float
    top_p: float
    max_tokens: int
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    supports_tools: bool = False


MODELS: dict[str, ModelSpec] = {
    "v4flash": ModelSpec(
        name="v4flash",
        deepinfra_id="deepseek-ai/DeepSeek-V4-Flash-0731",
        build=_build_v4,
        stop=[encoding_dsv4.eos_token],
        temperature=1.0,
        top_p=0.95,
        max_tokens=32_000,  # 16k truncated 2/9 parity attempts; model allows 384k output
        usd_per_mtok_in=0.06,  # DeepInfra list price, Sep 2026
        usd_per_mtok_out=0.18,
        supports_tools=True,
    ),
    "qwen3-32b": ModelSpec(
        name="qwen3-32b",
        deepinfra_id="Qwen/Qwen3-32B",
        build=_build_qwen3,
        stop=["<|im_end|>"],
        temperature=0.6,
        top_p=0.95,
        max_tokens=30_000,  # DeepInfra context is ~41k; leaves room for the prompt
        usd_per_mtok_in=0.08,
        usd_per_mtok_out=0.28,
    ),
}


def split_reasoning(prefill: str, continuation: str) -> tuple[str | None, str | None]:
    """Split generated text into reasoning and answer at the first `</think>`.

    @param prefill: The prefill the prompt ended with (it is the start of the reasoning).
    @param continuation: Raw text the model generated after the prompt.
    @returns: (reasoning, answer), both stripped; (None, None) if `</think>` never appears.
    """
    full = prefill + continuation
    if "</think>" not in full:
        return None, None
    reasoning, answer = full.split("</think>", 1)
    return reasoning.strip(), answer.strip()


def parse_v4_completion(
    prefill: str, continuation: str, finished: bool
) -> tuple[str, str, list[dict[str, Any]]]:
    """Parse a V4 thinking-mode completion into reasoning, content and tool calls.

    Uses DeepSeek's reference parser (DSML tool calls). The API strips our stop token
    (EOS), so it is re-appended when generation finished normally.

    @param prefill: The prefill the prompt ended with (start of the reasoning).
    @param continuation: Raw generated text after the prompt.
    @param finished: True if generation stopped on the stop token (not max_tokens).
    @returns: (reasoning, content, tool_calls) with tool_calls in OpenAI format
        ({"type", "function": {"name", "arguments": <JSON string>}}).
    @raises ValueError: If the text is malformed (e.g. no `</think>`, broken DSML).
    """
    text = prefill + continuation + (encoding_dsv4.eos_token if finished else "")
    try:
        msg = encoding_dsv4.parse_message_from_completion_text(text, "thinking")
    except (AssertionError, ValueError, IndexError) as ex:
        raise ValueError(f"unparseable V4 completion: {ex}") from ex
    return (
        msg["reasoning_content"].strip(),
        msg["content"].strip(),
        msg["tool_calls"],
    )


def normalize_prefill(prefill: str) -> str:
    """Strip trailing spaces/tabs, which make V4-Flash close `</think>` immediately (3/4 vs 0/4 runs)."""
    return prefill.rstrip(" \t")


def build_prompt(
    spec: ModelSpec,
    messages: list[Message],
    prefill: str = "",
    *,
    drop_thinking: bool = True,
    reasoning_effort: str | None = None,
) -> str:
    """Render messages to the model's raw prompt, ending inside an open reasoning block.

    The single place prompts are made; both the Inspect provider and scripts use it.

    @param spec: Model to render for (see MODELS).
    @param messages: See Message; roles system/user/assistant (+ tool, if spec.supports_tools).
    @param prefill: Text to start the reasoning with; trailing spaces are stripped.
    @param drop_thinking: If True, prior assistant turns' reasoning_content is omitted.
    @param reasoning_effort: V4 only: "low" | "high" | "max" (None = model default).
    @returns: Raw prompt string for the text-completions endpoint.
    """
    return spec.build(
        messages, normalize_prefill(prefill), drop_thinking, reasoning_effort
    )


def api_key() -> str:
    """Return DEEPINFRA_API_KEY from the environment or `.env`; raise if unset."""
    load_dotenv()
    key = os.environ.get("DEEPINFRA_API_KEY")
    if not key:
        raise RuntimeError("DEEPINFRA_API_KEY is not set (see .env.example)")
    return key
