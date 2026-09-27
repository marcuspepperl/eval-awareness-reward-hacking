"""Raw-prompt builders and a DeepInfra raw-completions client.

We build prompts ourselves (instead of using a chat API) so we can prefill the
model's reasoning block, e.g. inject an eval-awareness sentence mid-CoT.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

from earh.vendor import encoding_dsv4

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

Message = dict[str, str]


def _build_v4(
    messages: list[Message], prefill: str, drop_thinking: bool, reasoning_effort: str | None
) -> str:
    prompt = encoding_dsv4.encode_messages(
        messages,
        thinking_mode="thinking",
        drop_thinking=drop_thinking,
        reasoning_effort=reasoning_effort,
    )
    # encode_messages ends with "<｜Assistant｜><think>"; the prefill continues the reasoning.
    return prompt + prefill


def _build_qwen3(
    messages: list[Message], prefill: str, drop_thinking: bool, reasoning_effort: str | None
) -> str:
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
    name: str
    deepinfra_id: str
    build: Callable[[list[Message], str, bool, str | None], str]
    stop: list[str]
    temperature: float
    top_p: float


MODELS: dict[str, ModelSpec] = {
    "v4flash": ModelSpec(
        name="v4flash",
        deepinfra_id="deepseek-ai/DeepSeek-V4-Flash-0731",
        build=_build_v4,
        stop=[encoding_dsv4.eos_token],
        temperature=1.0,
        top_p=0.95,
    ),
    "qwen3-32b": ModelSpec(
        name="qwen3-32b",
        deepinfra_id="Qwen/Qwen3-32B",
        build=_build_qwen3,
        stop=["<|im_end|>"],
        temperature=0.6,
        top_p=0.95,
    ),
}


@dataclass
class Completion:
    prompt: str
    prefill: str
    continuation: str
    reasoning: (
        str | None
    )  # prefill + continued reasoning, None if </think> never appeared
    answer: str | None
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None


def split_reasoning(prefill: str, continuation: str) -> tuple[str | None, str | None]:
    full = prefill + continuation
    if "</think>" not in full:
        return None, None
    reasoning, answer = full.split("</think>", 1)
    return reasoning.strip(), answer.strip()


def normalize_prefill(prefill: str) -> str:
    # A trailing space tokenizes unnaturally: V4-Flash then closes </think> immediately
    # (3/4 runs in the smoke test vs 0/4 without it). Newlines are fine.
    return prefill.rstrip(" \t")


def build_prompt(
    spec: ModelSpec,
    messages: list[Message],
    prefill: str = "",
    *,
    drop_thinking: bool = True,
    reasoning_effort: str | None = None,
) -> str:
    """Render messages to the model's raw prompt, ending inside an open reasoning block + prefill.

    Assistant messages may carry a "reasoning_content" key; it is kept only if drop_thinking=False.
    """
    return spec.build(messages, normalize_prefill(prefill), drop_thinking, reasoning_effort)


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("DEEPINFRA_API_KEY")
    if not key:
        raise RuntimeError("DEEPINFRA_API_KEY is not set (see .env.example)")
    return key


def client() -> OpenAI:
    return OpenAI(api_key=api_key(), base_url=DEEPINFRA_BASE_URL)


def complete(
    spec: ModelSpec,
    messages: list[Message],
    prefill: str = "",
    *,
    drop_thinking: bool = True,
    reasoning_effort: str | None = None,
    max_tokens: int = 8000,
    api: OpenAI | None = None,
) -> Completion:
    prefill = normalize_prefill(prefill)
    prompt = build_prompt(
        spec, messages, prefill, drop_thinking=drop_thinking, reasoning_effort=reasoning_effort
    )
    resp = (api or client()).completions.create(
        model=spec.deepinfra_id,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=spec.temperature,
        top_p=spec.top_p,
        stop=spec.stop,
    )
    choice = resp.choices[0]
    reasoning, answer = split_reasoning(prefill, choice.text)
    return Completion(
        prompt=prompt,
        prefill=prefill,
        continuation=choice.text,
        reasoning=reasoning,
        answer=answer,
        prompt_tokens=resp.usage.prompt_tokens,
        completion_tokens=resp.usage.completion_tokens,
        finish_reason=choice.finish_reason,
    )
