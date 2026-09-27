"""Inspect model provider for DeepInfra raw completions with CoT prefill.

Usage: --model deepinfra-raw/v4flash  or  --model deepinfra-raw/qwen3-32b
Model args (-M): drop_thinking (bool, default True), reasoning_effort (V4 only: low|high|max),
                 max_connections (int, default 32).

Prefill convention: if the last input message is an assistant message with
metadata {"cot_prefill": True}, its text is used as the start of the reasoning
block and the model continues from there. The returned reasoning includes the
prefill, so logs show the full CoT the model "wrote". Solvers should remove the
prefill message after generate() (see earh.solver) so it isn't duplicated.
"""

from __future__ import annotations

import time
from typing import Any

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ContentReasoning,
    ContentText,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._openai import openai_should_retry
from inspect_ai.solver import Generate, TaskState
from inspect_ai.tool import ToolChoice, ToolInfo
from openai import AsyncOpenAI

from earh.models import (
    DEEPINFRA_BASE_URL,
    MODELS,
    Message,
    build_prompt,
    normalize_prefill,
    split_reasoning,
)
from earh.models import api_key as deepinfra_api_key

PREFILL_KEY = "cot_prefill"
DEFAULT_MAX_TOKENS = 16_000


def prefill_message(text: str) -> ChatMessageAssistant:
    """An assistant message the provider will treat as the start of the reasoning block."""
    return ChatMessageAssistant(content=text, metadata={PREFILL_KEY: True})


def is_prefill(message: ChatMessage) -> bool:
    return message.role == "assistant" and bool(
        (message.metadata or {}).get(PREFILL_KEY)
    )


async def generate_with_prefill(
    state: TaskState, generate: Generate, prefill: str
) -> TaskState:
    """generate() with the reasoning block prefilled; leaves no prefill message in history."""
    if not prefill:
        return await generate(state)
    state.messages.append(prefill_message(prefill))
    state = await generate(state)
    # generate() appended the model's reply after our prefill message; drop the prefill
    # (the reply's reasoning already starts with it).
    del state.messages[-2]
    return state


def _to_messages(input: list[ChatMessage]) -> list[Message]:
    out: list[Message] = []
    for m in input:
        if m.role not in ("system", "user", "assistant"):
            raise ValueError(f"deepinfra-raw does not support {m.role!r} messages")
        msg: Message = {"role": m.role, "content": m.text}
        if m.role == "assistant" and not isinstance(m.content, str):
            reasoning = "\n".join(
                c.reasoning for c in m.content if isinstance(c, ContentReasoning)
            )
            if reasoning:
                msg["reasoning_content"] = reasoning
        out.append(msg)
    return out


class DeepInfraRawAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        drop_thinking: bool = True,
        reasoning_effort: str | None = None,
        max_connections: int = 32,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url or DEEPINFRA_BASE_URL,
            api_key=api_key,
            api_key_vars=["DEEPINFRA_API_KEY"],
            config=config,
        )
        if model_name not in MODELS:
            raise ValueError(
                f"unknown model {model_name!r}; expected one of {list(MODELS)}"
            )
        self.spec = MODELS[model_name]
        self.drop_thinking = drop_thinking
        self.reasoning_effort = reasoning_effort
        self._max_connections = max_connections
        self.client = AsyncOpenAI(
            api_key=self.api_key or deepinfra_api_key(), base_url=self.base_url
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput, ModelCall]:
        if tools:
            raise ValueError("deepinfra-raw does not support tools")

        prefill = ""
        if input and is_prefill(input[-1]):
            prefill = normalize_prefill(input[-1].text)
            input = input[:-1]

        prompt = build_prompt(
            self.spec,
            _to_messages(input),
            prefill,
            drop_thinking=self.drop_thinking,
            reasoning_effort=self.reasoning_effort,
        )
        request: dict[str, Any] = dict(
            model=self.spec.deepinfra_id,
            prompt=prompt,
            max_tokens=config.max_tokens or DEFAULT_MAX_TOKENS,
            temperature=config.temperature
            if config.temperature is not None
            else self.spec.temperature,
            top_p=config.top_p if config.top_p is not None else self.spec.top_p,
            stop=self.spec.stop,
        )
        if config.seed is not None:
            request["seed"] = config.seed

        start = time.monotonic()
        resp = await self.client.completions.create(**request)
        choice = resp.choices[0]

        reasoning, answer = split_reasoning(prefill, choice.text)
        if (
            reasoning is None
        ):  # never closed </think> (usually hit max_tokens): all of it is reasoning
            reasoning, answer = (prefill + choice.text).strip(), ""
        message = ChatMessageAssistant(
            content=[ContentReasoning(reasoning=reasoning), ContentText(text=answer)],
            model=self.spec.deepinfra_id,
            source="generate",
            metadata={"prefill": prefill} if prefill else None,
        )
        usage = resp.usage
        output = ModelOutput(
            model=self.spec.deepinfra_id,
            choices=[
                ChatCompletionChoice(
                    message=message,
                    stop_reason="max_tokens"
                    if choice.finish_reason == "length"
                    else "stop",
                )
            ],
            usage=ModelUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
            if usage
            else None,
            time=time.monotonic() - start,
        )
        return output, ModelCall.create(request=request, response=resp.model_dump())

    def should_retry(self, ex: BaseException) -> bool:
        return openai_should_retry(ex)

    def max_connections(self) -> int:
        return self._max_connections

    def connection_key(self) -> str:
        return self.spec.deepinfra_id
