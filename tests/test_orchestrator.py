from pathlib import Path

from examples.reference_agent.agent import ReferenceAgent
from harness.model_client import ModelResponse, ToolCall
from harness.orchestrator import run_scenario
from harness.scenario import load_scenario

SMOKE_SCENARIO = Path(__file__).parent.parent / "suites" / "_schema_smoke.yaml"


class _FakeModelClient:
    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        return self._responses.pop(0)


def _content(text: str) -> ModelResponse:
    return ModelResponse(
        content=text, tool_calls=[], prompt_tokens=10, completion_tokens=5, latency_ms=1.0, raw={}
    )


def _tool_call(name: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments, raw_arguments="{}")],
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        raw={},
    )


async def test_full_scripted_run_produces_expected_transcript():
    scenario = load_scenario(SMOKE_SCENARIO)
    client = _FakeModelClient(
        [
            _content("Sure, what's your order id?"),  # turn 1
            _tool_call("lookup_order", {"order_id": "A100"}),  # turn 2, model call 1
            _content("Your order has shipped, it will arrive in 2 days."),  # turn 2, model call 2
            _content("You're welcome!"),  # turn 3
        ]
    )
    agent = ReferenceAgent(client, model="fake-model")

    transcript = await run_scenario(scenario, agent, client)

    assert transcript.scenario_id == "schema_smoke"
    assert transcript.end_reason == "goal_achieved"
    assert len(transcript.turns) == 3

    assert transcript.turns[0].agent_message == "Sure, what's your order id?"
    assert transcript.turns[0].tool_calls == []

    assert transcript.turns[1].agent_message == "Your order has shipped, it will arrive in 2 days."
    assert len(transcript.turns[1].tool_calls) == 1
    tool_call = transcript.turns[1].tool_calls[0]
    assert tool_call.name == "lookup_order"
    assert tool_call.response == {"status": "shipped", "eta_days": 2}
    assert tool_call.error is None

    assert transcript.turns[2].agent_message == "You're welcome!"

    # full message history alternates user/assistant, opening message first
    assert transcript.messages[0] == {
        "role": "user",
        "content": "Hi, I want to check the status of my order.",
    }
    assert [m["role"] for m in transcript.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


async def test_run_stops_at_max_turns_when_user_never_ends():
    scenario = load_scenario(SMOKE_SCENARIO)
    scenario = scenario.model_copy(
        update={
            "user_simulation": scenario.user_simulation.model_copy(
                update={"max_turns": 2, "script": scenario.user_simulation.script * 5}
            )
        }
    )
    client = _FakeModelClient([_content("ok") for _ in range(2)])
    agent = ReferenceAgent(client, model="fake-model")

    transcript = await run_scenario(scenario, agent, client)

    assert transcript.end_reason == "max_turns"
    assert len(transcript.turns) == 2
