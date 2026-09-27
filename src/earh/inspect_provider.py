"""Inspect model provider for DeepInfra raw completions with CoT prefill.

Usage: --model deepinfra-raw/v4flash  or  --model deepinfra-raw/qwen3-32b
Model args (-M): drop_thinking (bool, default True), reasoning_effort (V4 only: low|high|max),
                 max_connections (int, default 32).

Prefill convention: if the last input message is an assistant message with
metadata {"cot_prefill": True}, its text is used as the start of the reasoning
block and the model continues from there. The returned reasoning includes the
prefill, so logs show the full CoT the model "wrote". Solvers should remove the
prefill message after generate() (generate_with_prefill does this).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
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
# We stream responses: long non-streaming requests (~20 min for 30k Qwen3 tokens at
# ~25 tok/s) exceeded the SDK's 600s default and later hung silently. With streaming,
# the read timeout bounds the gap between chunks rather than the whole generation.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=60.0)


def prefill_message(text: str) -> ChatMessageAssistant:
    """An assistant message the provider will treat as the start of the reasoning block."""
    return ChatMessageAssistant(content=text, metadata={PREFILL_KEY: True})


def is_prefill(message: ChatMessage) -> bool:
    """Whether a message is a prefill marker created by prefill_message()."""
    return message.role == "assistant" and bool(
        (message.metadata or {}).get(PREFILL_KEY)
    )


async def generate_with_prefill(
    state: TaskState, generate: Generate, prefill: str
) -> TaskState:
    """Call generate() with the model's reasoning block prefilled.

    Appends a prefill marker, generates, then removes the marker so history holds only
    the model's reply (whose reasoning already starts with the prefill).

    @param state: Current task state; its messages are mutated.
    @param generate: Inspect's generate function passed to the solver.
    @param prefill: Text to start the reasoning with ("" = plain generate).
    @returns: The updated task state.
    """
    if not prefill:
        return await generate(state)
    state.messages.append(prefill_message(prefill))
    state = await generate(state)
    # generate() appended the model's reply after our prefill message; drop the prefill
    # (the reply's reasoning already starts with it).
    del state.messages[-2]
    return state


def _to_messages(input: list[ChatMessage]) -> list[Message]:
    """Convert Inspect messages to builder dicts, carrying assistant reasoning as reasoning_content."""
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
    """Inspect ModelAPI that renders chats to raw prompts and calls DeepInfra /completions."""

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
        """Create the provider (Inspect calls this once per eval per model).

        @param model_name: Key in MODELS, e.g. "v4flash" (from --model deepinfra-raw/<name>).
        @param base_url: Override DeepInfra's OpenAI-compatible base URL.
        @param api_key: Override DEEPINFRA_API_KEY.
        @param config: Inspect generation config defaults.
        @param drop_thinking: Omit prior turns' reasoning from prompts (-M drop_thinking=...).
        @param reasoning_effort: V4 only: "low" | "high" | "max".
        @param max_connections: Concurrent request cap for this model.
        @param model_args: Unused extra -M args.
        """
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
        # max_retries=0: Inspect owns retries (via should_retry), so they are logged.
        self.client = AsyncOpenAI(
            api_key=self.api_key or deepinfra_api_key(),
            base_url=self.base_url,
            timeout=STREAM_TIMEOUT,
            max_retries=0,
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput, ModelCall]:
        """Generate one assistant turn (called once per Inspect generate()).

        A trailing prefill marker (see prefill_message) becomes the start of the
        reasoning block. Output reasoning includes the prefill; if `</think>` never
        appears (usually max_tokens), all text is treated as reasoning with an empty answer.

        @param input: Conversation so far, optionally ending with a prefill marker.
        @param tools: Must be empty; tools are not supported.
        @param tool_choice: Ignored.
        @param config: Per-call generation config (max_tokens, temperature, top_p, seed).
        @returns: (ModelOutput with ContentReasoning + ContentText, ModelCall with the raw request).
        """
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
            max_tokens=config.max_tokens or self.spec.max_tokens,
            temperature=config.temperature
            if config.temperature is not None
            else self.spec.temperature,
            top_p=config.top_p if config.top_p is not None else self.spec.top_p,
            stop=self.spec.stop,
        )
        if config.seed is not None:
            request["seed"] = config.seed

        start = time.monotonic()
        text, finish_reason, usage = await self._stream(request)

        reasoning, answer = split_reasoning(prefill, text)
        if reasoning is None:
            reasoning, answer = (prefill + text).strip(), ""
        message = ChatMessageAssistant(
            content=[ContentReasoning(reasoning=reasoning), ContentText(text=answer)],
            model=self.spec.deepinfra_id,
            source="generate",
            metadata={"prefill": prefill} if prefill else None,
        )
        output = ModelOutput(
            model=self.spec.deepinfra_id,
            choices=[
                ChatCompletionChoice(
                    message=message,
                    stop_reason="max_tokens" if finish_reason == "length" else "stop",
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
        response = dict(
            text=text,
            finish_reason=finish_reason,
            usage=usage.model_dump() if usage else None,
        )
        return output, ModelCall.create(request=request, response=response)

    async def _stream(self, request: dict[str, Any]) -> tuple[str, str | None, Any]:
        """Stream one completion and return (text, finish_reason, usage)."""
        stream = await self.client.completions.create(
            **request, stream=True, stream_options={"include_usage": True}
        )
        chunks: list[str] = []
        finish_reason, usage = None, None
        async for chunk in stream:
            if chunk.choices:
                chunks.append(chunk.choices[0].text or "")
                finish_reason = chunk.choices[0].finish_reason or finish_reason
            if chunk.usage:
                usage = chunk.usage
        return "".join(chunks), finish_reason, usage

    def should_retry(self, ex: BaseException) -> bool:
        """Retry the same transient errors as Inspect's OpenAI provider."""
        return openai_should_retry(ex)

    def max_connections(self) -> int:
        """Concurrent request cap (from the max_connections model arg)."""
        return self._max_connections

    def connection_key(self) -> str:
        """Pool concurrency per DeepInfra model ID."""
        return self.spec.deepinfra_id
