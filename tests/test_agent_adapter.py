from examples.reference_agent.agent import ReferenceAgent
from harness.model_client import ModelResponse, ToolCall
from harness.transcript import ToolCallRecord


class _FakeModelClient:
    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self._responses.pop(0)


class _FakeExecutor:
    def __init__(self, response: dict):
        self._response = response
        self.executed: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolCallRecord:
        self.executed.append(tool_call)
        return ToolCallRecord(
            id=tool_call.id,
            name=tool_call.name,
            arguments=tool_call.arguments,
            response=self._response,
        )


def _content_response(text: str) -> ModelResponse:
    return ModelResponse(
        content=text, tool_calls=[], prompt_tokens=10, completion_tokens=5, latency_ms=1.0, raw={}
    )


def _tool_call_response(name: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments, raw_arguments="{}")],
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        raw={},
    )


async def test_returns_content_directly_when_model_makes_no_tool_calls():
    client = _FakeModelClient([_content_response("hello, how can I help?")])
    agent = ReferenceAgent(client, model="gpt-4o-mini")
    executor = _FakeExecutor(response={})

    result = await agent.take_turn([{"role": "user", "content": "hi"}], tools=[], executor=executor)

    assert result.assistant_message == "hello, how can I help?"
    assert result.tool_calls == []
    assert executor.executed == []


async def test_executes_tool_call_and_reprompts_with_result():
    client = _FakeModelClient(
        [
            _tool_call_response("lookup_order", {"order_id": "A100"}),
            _content_response("Your order has shipped."),
        ]
    )
    agent = ReferenceAgent(client, model="gpt-4o-mini")
    executor = _FakeExecutor(response={"status": "shipped"})

    result = await agent.take_turn(
        [{"role": "user", "content": "where's my order?"}], tools=[], executor=executor
    )

    assert result.assistant_message == "Your order has shipped."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].response == {"status": "shipped"}
    assert len(executor.executed) == 1

    # second model call's message history includes the tool result
    second_call_messages = client.calls[1]["messages"]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "shipped" in tool_messages[0]["content"]


async def test_iteration_cap_returns_whatever_was_collected():
    responses = [_tool_call_response("lookup_order", {"order_id": "A100"}) for _ in range(5)]
    client = _FakeModelClient(responses)
    agent = ReferenceAgent(client, model="gpt-4o-mini", max_tool_iterations=5)
    executor = _FakeExecutor(response={"status": "shipped"})

    result = await agent.take_turn([{"role": "user", "content": "hi"}], tools=[], executor=executor)

    assert result.assistant_message == ""
    assert len(result.tool_calls) == 5
    assert len(client.calls) == 5
