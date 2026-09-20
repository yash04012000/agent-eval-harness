"""Model-provider abstraction (PRD 1).

Every model call in the harness -- agent, simulated user, judge -- goes through this one
interface, backed by LiteLLM so any OpenAI-compatible endpoint and local Ollama models work
without provider-specific code elsewhere in the harness.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import litellm
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


class ModelResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    raw: dict[str, Any]


class ModelClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> ModelResponse: ...


def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tc in raw_tool_calls or []:
        raw_args = tc.function.arguments or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
        calls.append(
            ToolCall(id=tc.id, name=tc.function.name, arguments=args, raw_arguments=raw_args)
        )
    return calls


class LiteLLMModelClient:
    """Default `ModelClient` -- routes every call through `litellm.acompletion`."""

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> ModelResponse:
        start = time.perf_counter()
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            **kwargs,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        choice = response.choices[0].message
        usage = response.usage

        return ModelResponse(
            content=choice.content,
            tool_calls=_parse_tool_calls(getattr(choice, "tool_calls", None)),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
            raw=response.model_dump() if hasattr(response, "model_dump") else dict(response),
        )
