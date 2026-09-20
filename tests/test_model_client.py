import litellm
import pytest

from harness.model_client import LiteLLMModelClient


class _FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeCompletionResponse:
    def __init__(self, message: _FakeMessage, usage: _FakeUsage):
        self.choices = [_FakeChoice(message)]
        self.usage = usage

    def model_dump(self):
        return {"fake": "raw-response"}


@pytest.fixture
def client():
    return LiteLLMModelClient()


async def test_complete_returns_content_and_usage(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeCompletionResponse(_FakeMessage("hello there"), _FakeUsage(10, 5))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    response = await client.complete(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )

    assert response.content == "hello there"
    assert response.tool_calls == []
    assert response.prompt_tokens == 10
    assert response.completion_tokens == 5
    assert response.latency_ms >= 0
    assert response.raw == {"fake": "raw-response"}


async def test_complete_parses_valid_tool_call_arguments(client, monkeypatch):
    tool_call = _FakeToolCall("call_1", "lookup_order", '{"order_id": "A100"}')

    async def fake_acompletion(**kwargs):
        return _FakeCompletionResponse(_FakeMessage(None, [tool_call]), _FakeUsage(20, 8))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    response = await client.complete(model="gpt-4o-mini", messages=[])

    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "lookup_order"
    assert call.arguments == {"order_id": "A100"}
    assert call.raw_arguments == '{"order_id": "A100"}'


async def test_complete_handles_malformed_tool_call_arguments(client, monkeypatch):
    tool_call = _FakeToolCall("call_1", "lookup_order", "{not valid json")

    async def fake_acompletion(**kwargs):
        return _FakeCompletionResponse(_FakeMessage(None, [tool_call]), _FakeUsage(20, 8))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    response = await client.complete(model="gpt-4o-mini", messages=[])

    call = response.tool_calls[0]
    assert call.arguments == {}
    assert call.raw_arguments == "{not valid json"
