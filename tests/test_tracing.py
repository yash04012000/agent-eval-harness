from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import harness.tracing as tracing_module
from harness.model_client import ModelResponse
from harness.tracing import instrument_model_client, instrument_tool_executor
from harness.transcript import ToolCallRecord


def _install_in_memory_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing_module._provider_override = provider
    return exporter


class _FakeModelClient:
    last_cache_hit = True

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        return ModelResponse(
            content="hi", tool_calls=[], prompt_tokens=10, completion_tokens=5, latency_ms=2.0,
            raw={},
        )


class _FakeExecutor:
    def execute(self, tool_call):
        return ToolCallRecord(id=tool_call.id, name=tool_call.name, arguments={}, latency_ms=1.5)


async def test_instrumented_model_client_emits_model_call_span():
    exporter = _install_in_memory_exporter()
    client = instrument_model_client(_FakeModelClient())

    await client.complete(model="fake-model", messages=[{"role": "user", "content": "hi"}])

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "model_call"
    assert span.attributes["model"] == "fake-model"
    assert span.attributes["prompt_tokens"] == 10
    assert span.attributes["completion_tokens"] == 5
    assert span.attributes["cache_hit"] is True


def test_instrumented_tool_executor_emits_tool_call_span():
    exporter = _install_in_memory_exporter()
    executor = instrument_tool_executor(_FakeExecutor())

    class _Call:
        id = "c1"
        name = "lookup_order"

    executor.execute(_Call())

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "tool_call"
    assert spans[0].attributes["tool_name"] == "lookup_order"
    assert "error" not in spans[0].attributes
