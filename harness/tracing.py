"""OpenTelemetry spans around every model call and tool call (PRD 5).

Wraps the two seams that already exist as single functions from PRD 1/2 -- `ModelClient.complete`
and `ToolMockExecutor.execute` -- by rebinding the *instance* method to a traced wrapper, so no
call site in PRDs 1-4 needs to change; tracing is added around them, not threaded through them.

Span tree: run -> scenario -> turn -> {model_call | tool_call} (the run/scenario/turn spans are
opened by whichever caller owns that scope -- `run_suite`/`run_scenario` when tracing is enabled).
"""

from __future__ import annotations

import types
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from harness.model_client import ModelClient, ModelResponse
from harness.tool_executor import ToolMockExecutor
from harness.transcript import ToolCallRecord

_TRACER_NAME = "agent_eval_harness"

Exporter = Literal["console", "otlp", "none"]

# The OpenTelemetry SDK only allows `trace.set_tracer_provider` to be called once per process, so
# a module-level override lets `setup_tracing` (and tests) swap providers freely without hitting
# that restriction -- `get_tracer` prefers this when set, falling back to the global provider.
_provider_override: TracerProvider | None = None


def setup_tracing(exporter: Exporter = "none") -> TracerProvider | None:
    """Configures the tracer provider used by `get_tracer`. Returns None (no tracing) for "none"."""
    global _provider_override
    if exporter == "none":
        _provider_override = None
        return None

    provider = TracerProvider(resource=Resource.create({"service.name": "agent-eval-harness"}))
    if exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "otlp":
        # Imported lazily -- the otlp exporter pulls in grpc/http transport deps not needed
        # unless this exporter is actually selected.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    _provider_override = provider
    return provider


def get_tracer():
    provider = _provider_override or trace.get_tracer_provider()
    return provider.get_tracer(_TRACER_NAME)


def _traced_complete(
    inner: Callable[..., Awaitable[ModelResponse]],
) -> Callable[..., Awaitable[ModelResponse]]:
    async def wrapper(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> ModelResponse:
        tracer = get_tracer()
        with tracer.start_as_current_span("model_call") as span:
            span.set_attribute("model", model)
            response = await inner(
                self, model, messages, tools=tools, temperature=temperature, **kwargs
            )
            cache_hit = getattr(self, "last_cache_hit", None)
            if cache_hit is not None:
                span.set_attribute("cache_hit", cache_hit)
            span.set_attribute("prompt_tokens", response.prompt_tokens)
            span.set_attribute("completion_tokens", response.completion_tokens)
            span.set_attribute("latency_ms", response.latency_ms)
            return response

    return wrapper


def _traced_execute(
    inner: Callable[..., ToolCallRecord],
) -> Callable[..., ToolCallRecord]:
    def wrapper(self, tool_call) -> ToolCallRecord:
        tracer = get_tracer()
        with tracer.start_as_current_span("tool_call") as span:
            span.set_attribute("tool_name", tool_call.name)
            record = inner(self, tool_call)
            if record.error:
                span.set_attribute("error", record.error)
            span.set_attribute("latency_ms", record.latency_ms)
            return record

    return wrapper


def instrument_model_client(client: ModelClient) -> ModelClient:
    """Rebinds `client.complete` to a traced wrapper. Returns `client` for chaining."""
    client.complete = types.MethodType(_traced_complete(type(client).complete), client)  # type: ignore[method-assign]
    return client


def instrument_tool_executor(executor: ToolMockExecutor) -> ToolMockExecutor:
    """Rebinds `executor.execute` to a traced wrapper. Returns `executor` for chaining."""
    executor.execute = types.MethodType(_traced_execute(type(executor).execute), executor)  # type: ignore[method-assign]
    return executor
