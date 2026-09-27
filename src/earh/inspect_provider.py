"""Inspect model provider for DeepInfra raw completions with CoT prefill.

Usage: --model deepinfra-raw/v4flash  or  --model deepinfra-raw/qwen3-32b
Tools: supported for models with spec.supports_tools (V4-Flash, via DSML). With tools,
V4's encoder keeps all prior reasoning in context (drop_thinking is auto-disabled).
Model args (-M): drop_thinking (bool, default True), reasoning_effort (V4 only: low|high|max),
                 max_connections (int, default 32).

Prefill convention: if the last input message is an assistant message with
metadata {"cot_prefill": True}, its text is used as the start of the reasoning
block and the model continues from there. The returned reasoning includes the
prefill, so logs show the full CoT the model "wrote". Solvers should remove the
prefill message after generate() (generate_with_prefill does this).
"""

from __future__ import annotations

import json
import secrets
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
from inspect_ai.model._openai import openai_chat_tools, openai_should_retry
from inspect_ai.solver import Generate, TaskState
from inspect_ai.tool import ToolCall, ToolChoice, ToolInfo
from openai import AsyncOpenAI

from earh.models import (
    DEEPINFRA_BASE_URL,
    MODELS,
    Message,
    build_prompt,
    normalize_prefill,
    parse_v4_completion,
    split_reasoning,
)
from earh.models import api_key as deepinfra_api_key
from earh.vendor import encoding_dsv4

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
    state: TaskState, generate: Generate, prefill: str, **generate_kwargs: Any
) -> TaskState:
    """Call generate() with the model's reasoning block prefilled.

    Appends a prefill marker, generates, then removes the marker so history holds only
    the model's reply (whose reasoning already starts with the prefill) and any tool
    results. With tools, pass tool_calls="single" (not "loop"): the marker must be the
    last message only for the first model call.

    @param state: Current task state; its messages are mutated.
    @param generate: Inspect's generate function passed to the solver.
    @param prefill: Text to start the reasoning with ("" = plain generate).
    @param generate_kwargs: Passed through to generate (e.g. tool_calls="single").
    @returns: The updated task state.
    """
    if not prefill:
        return await generate(state, **generate_kwargs)
    marker = prefill_message(prefill)
    state.messages.append(marker)
    state = await generate(state, **generate_kwargs)
    state.messages = [m for m in state.messages if m is not marker]
    return state


def _to_messages(
    input: list[ChatMessage], tools: list[ToolInfo] | None = None
) -> list[Message]:
    """Convert Inspect messages to builder dicts (OpenAI-format tool fields).

    Assistant reasoning becomes reasoning_content (the builder decides whether to keep
    it); assistant tool calls and tool results are carried over; tool definitions are
    attached to the system message (one is created if absent), as V4's encoder expects.

    @param input: Inspect conversation.
    @param tools: Tool definitions offered to the model (None/empty = no tools).
    @returns: Message dicts for earh.models.build_prompt.
    """
    out: list[Message] = []
    for m in input:
        if m.role == "tool" and not tools:
            raise ValueError("deepinfra-raw got a tool message but no tools")
        msg: Message = {"role": m.role, "content": m.text}
        if m.role == "assistant":
            if not isinstance(m.content, str):
                reasoning = "\n".join(
                    c.reasoning for c in m.content if isinstance(c, ContentReasoning)
                )
                if reasoning:
                    msg["reasoning_content"] = reasoning
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "type": "function",
                        "id": tc.id,
                        "function": {
                            "name": tc.function,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
        elif m.role == "tool":
            msg["tool_call_id"] = m.tool_call_id or ""
            if m.error:
                msg["content"] = (m.text + "\n" if m.text else "") + (
                    f"Error: {m.error.message}"
                )
        out.append(msg)
    if tools:
        if not out or out[0]["role"] != "system":
            out.insert(0, {"role": "system", "content": ""})
        out[0]["tools"] = [dict(t) for t in openai_chat_tools(tools)]
    return out


def _to_tool_calls(openai_calls: list[dict[str, Any]]) -> list[ToolCall]:
    """Convert parsed OpenAI-format tool calls to Inspect ToolCalls (bad JSON -> parse_error)."""
    calls = []
    for c in openai_calls:
        fn = c["function"]
        call_id = f"call_{secrets.token_hex(6)}"
        try:
            args = json.loads(fn["arguments"])
            calls.append(ToolCall(id=call_id, function=fn["name"], arguments=args))
        except json.JSONDecodeError as ex:
            calls.append(
                ToolCall(
                    id=call_id,
                    function=fn["name"],
                    arguments={},
                    parse_error=f"Invalid tool call arguments: {ex}",
                )
            )
    return calls


def _parse_with_tools(
    prefill: str, text: str, finish_reason: str | None
) -> tuple[str, str, list[ToolCall], str | None]:
    """Parse a tools-enabled V4 completion; never raises.

    Truncated output (no `</think>`) becomes all-reasoning with no calls. If the output
    looks like a tool call but is malformed, we return one placeholder ToolCall with
    parse_error set, so Inspect reports the error to the model and the loop continues.

    @param prefill: Prefill the prompt ended with.
    @param text: Generated continuation.
    @param finish_reason: API finish reason ("stop" | "length" | None).
    @returns: (reasoning, answer, tool_calls, parse_error or None).
    """
    try:
        reasoning, answer, calls = parse_v4_completion(
            prefill, text, finished=finish_reason != "length"
        )
        return reasoning, answer, _to_tool_calls(calls), None
    except ValueError as ex:
        full = prefill + text
        reasoning, _, rest = full.partition("</think>")
        if finish_reason == "length" or not rest:
            return full.strip(), "", [], None
        if f"<{encoding_dsv4.dsml_token}" not in rest:  # plain answer, just unparseable
            return reasoning.strip(), rest.strip(), [], None
        error = f"Malformed tool call ({ex}). Use the exact tool-call format."
        placeholder = ToolCall(
            id=f"call_{secrets.token_hex(6)}",
            function="unparsed_tool_call",
            arguments={},
            parse_error=error,
        )
        return reasoning.strip(), rest.strip(), [placeholder], str(ex)


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
        @param tools: Tool definitions (only for models with spec.supports_tools).
        @param tool_choice: Ignored (the model decides; "none" is not enforced).
        @param config: Per-call generation config (max_tokens, temperature, top_p, seed).
        @returns: (ModelOutput with ContentReasoning + ContentText, ModelCall with the raw request).
        """
        if tools and not self.spec.supports_tools:
            raise ValueError(f"deepinfra-raw/{self.spec.name} does not support tools")

        prefill = ""
        if input and is_prefill(input[-1]):
            prefill = normalize_prefill(input[-1].text)
            input = input[:-1]

        prompt = build_prompt(
            self.spec,
            _to_messages(input, tools),
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

        metadata: dict[str, Any] = {"prefill": prefill} if prefill else {}
        tool_calls: list[ToolCall] = []
        if tools:
            reasoning, answer, tool_calls, parse_error = _parse_with_tools(
                prefill, text, finish_reason
            )
            if parse_error:
                metadata["tool_parse_error"] = parse_error
        else:
            reasoning, answer = split_reasoning(prefill, text)
            if reasoning is None:
                reasoning, answer = (prefill + text).strip(), ""
        message = ChatMessageAssistant(
            content=[ContentReasoning(reasoning=reasoning), ContentText(text=answer)],
            tool_calls=tool_calls or None,
            model=self.spec.deepinfra_id,
            source="generate",
            metadata=metadata or None,
        )
        if finish_reason == "length":
            stop_reason = "max_tokens"
        elif tool_calls:
            stop_reason = "tool_calls"
        else:
            stop_reason = "stop"
        output = ModelOutput(
            model=self.spec.deepinfra_id,
            choices=[ChatCompletionChoice(message=message, stop_reason=stop_reason)],
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
