"""Model registry and raw-prompt rendering for DeepInfra's text-completions endpoint.

We render prompts ourselves (instead of using a chat API) so we can prefill the
model's reasoning block, e.g. inject an eval-awareness sentence mid-CoT.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from dotenv import load_dotenv

from earh.vendor import encoding_dsv4

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

Message = dict[str, str]


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
    """Static per-model config: DeepInfra ID, prompt builder, stop tokens, sampling/length defaults."""

    name: str
    deepinfra_id: str
    build: Callable[[list[Message], str, bool, str | None], str]
    stop: list[str]
    temperature: float
    top_p: float
    max_tokens: int


MODELS: dict[str, ModelSpec] = {
    "v4flash": ModelSpec(
        name="v4flash",
        deepinfra_id="deepseek-ai/DeepSeek-V4-Flash-0731",
        build=_build_v4,
        stop=[encoding_dsv4.eos_token],
        temperature=1.0,
        top_p=0.95,
        max_tokens=32_000,  # 16k truncated 2/9 parity attempts; model allows 384k output
    ),
    "qwen3-32b": ModelSpec(
        name="qwen3-32b",
        deepinfra_id="Qwen/Qwen3-32B",
        build=_build_qwen3,
        stop=["<|im_end|>"],
        temperature=0.6,
        top_p=0.95,
        max_tokens=30_000,  # DeepInfra context is ~41k; leaves room for the prompt
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
    @param messages: [{role, content, reasoning_content?}]; roles system/user/assistant.
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
