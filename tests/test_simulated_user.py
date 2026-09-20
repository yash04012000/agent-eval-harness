from harness.model_client import ModelResponse, ToolCall
from harness.scenario import Difficulty, Persona, ScriptedTurn
from harness.simulated_user import ScriptedUser, SimulatedUser


class _FakeModelClient:
    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        return self._responses.pop(0)


def _tool_call_response(message, ended, end_reason=None) -> ModelResponse:
    return ModelResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="respond_as_user",
                arguments={"message": message, "ended": ended, "end_reason": end_reason},
                raw_arguments="{}",
            )
        ],
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        raw={},
    )


async def test_scripted_user_replays_script_in_order():
    user = ScriptedUser([ScriptedTurn(user="first"), ScriptedTurn(user="second")])
    turn1 = await user.next([])
    turn2 = await user.next([])
    turn3 = await user.next([])

    assert (turn1.message, turn1.ended) == ("first", False)
    assert (turn2.message, turn2.ended) == ("second", False)
    assert turn3.ended is True
    assert turn3.end_reason == "goal_achieved"


async def test_simulated_user_returns_message_from_structured_tool_call():
    client = _FakeModelClient([_tool_call_response("I need help with my order", False)])
    persona = Persona(name="Alex", goal="get help", difficulty=Difficulty.NORMAL)
    user = SimulatedUser(persona, model="gpt-4o-mini", max_turns=5, model_client=client)

    result = await user.next([{"role": "user", "content": "Hi, how can I help?"}])

    assert result.message == "I need help with my order"
    assert result.ended is False


async def test_simulated_user_ends_when_model_signals_goal_achieved():
    client = _FakeModelClient([_tool_call_response(None, True, "goal_achieved")])
    persona = Persona(name="Alex", goal="get help", difficulty=Difficulty.NORMAL)
    user = SimulatedUser(persona, model="gpt-4o-mini", max_turns=5, model_client=client)

    result = await user.next([])

    assert result.ended is True
    assert result.end_reason == "goal_achieved"


async def test_simulated_user_caps_at_max_turns_without_calling_model():
    client = _FakeModelClient([_tool_call_response("still going", False)])
    persona = Persona(name="Alex", goal="get help", difficulty=Difficulty.NORMAL)
    user = SimulatedUser(persona, model="gpt-4o-mini", max_turns=1, model_client=client)

    first = await user.next([])  # the one turn max_turns=1 allows
    assert first.ended is False
    assert len(client.calls) == 1

    second = await user.next([])  # over budget -- must not call the model again

    assert second.ended is True
    assert second.end_reason == "max_turns"
    assert len(client.calls) == 1


async def test_flips_roles_so_simulator_sees_agent_as_user():
    client = _FakeModelClient([_tool_call_response("ok", False)])
    persona = Persona(name="Alex", goal="get help", difficulty=Difficulty.NORMAL)
    user = SimulatedUser(persona, model="gpt-4o-mini", max_turns=5, model_client=client)

    await user.next(
        [
            {"role": "user", "content": "my own past message"},
            {"role": "assistant", "content": "agent reply"},
        ]
    )

    sent = client.calls[0]["messages"]
    # system prompt first, then the flipped history
    assert sent[1] == {"role": "assistant", "content": "my own past message"}
    assert sent[2] == {"role": "user", "content": "agent reply"}
