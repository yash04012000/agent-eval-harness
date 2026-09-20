import asyncio

from harness.agent_adapter import AgentTurnResult
from harness.cache import CacheMode
from harness.model_client import ModelResponse
from harness.run import RunConfig, build_model_client, run_suite
from harness.scenario import ExpectedOutcome, Scenario, ScriptedTurn, UserSimulation


def _scripted_scenario(scenario_id: str) -> Scenario:
    return Scenario(
        id=scenario_id,
        intent="test",
        description="test scenario",
        opening_message="hi",
        user_simulation=UserSimulation(mode="scripted", script=[ScriptedTurn(user="bye")]),
        expected_outcome=ExpectedOutcome(resolution="resolved"),
    )


class _ConcurrencyTrackingAgent:
    def __init__(self):
        self.current = 0
        self.max_seen = 0

    async def take_turn(self, messages, tools, executor):
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)
        await asyncio.sleep(0.05)
        self.current -= 1
        return AgentTurnResult(assistant_message="ok", tool_calls=[])


class _FakeInnerModelClient:
    def __init__(self, prompt_tokens: int = 50, completion_tokens: int = 50):
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        return ModelResponse(
            content="ok",
            tool_calls=[],
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            latency_ms=0.1,
            raw={},
        )


class _BudgetConsumingAgent:
    """Every turn spends one model call's worth of (fake) tokens against the shared tracker."""

    def __init__(self, model_client):
        self._client = model_client

    async def take_turn(self, messages, tools, executor):
        await self._client.complete(model="fake", messages=messages)
        return AgentTurnResult(assistant_message="ok", tool_calls=[])


async def test_concurrency_limit_is_respected():
    scenarios = [_scripted_scenario(f"s{i}") for i in range(6)]
    agent = _ConcurrencyTrackingAgent()
    config = RunConfig(concurrency_limit=2)
    model_client, tracker = build_model_client(config, inner_client=_FakeInnerModelClient())

    result = await run_suite(scenarios, agent, config, model_client, tracker)

    assert agent.max_seen <= 2
    assert agent.max_seen == 2  # six scenarios under a limit of 2 should actually overlap
    assert len(result.outcomes) == 6
    assert all(o.status == "completed" for o in result.outcomes)
    assert result.aborted is False


async def test_budget_abort_marks_remaining_scenarios_aborted():
    scenarios = [_scripted_scenario(f"s{i}") for i in range(4)]
    config = RunConfig(concurrency_limit=1, total_token_budget=250, cache_mode=CacheMode.LIVE)
    model_client, tracker = build_model_client(
        config, inner_client=_FakeInnerModelClient(prompt_tokens=50, completion_tokens=50)
    )
    agent = _BudgetConsumingAgent(model_client)

    result = await run_suite(scenarios, agent, config, model_client, tracker)

    assert result.aborted is True
    statuses = {o.scenario_id: o.status for o in result.outcomes}
    # s0 (2 turns * 100 tokens = 200) is always allowed to finish under concurrency_limit=1 --
    # nothing else can even acquire the semaphore until it's done.
    assert statuses["s0"] == "completed"
    # whichever call first pushes the running total past 250 aborts the run; with near-instant
    # fake calls, exactly how many *other* scenarios also race ahead before cancellation lands is
    # not deterministic, but at least one must be aborted and none can silently vanish.
    assert result.aborted is True
    assert "aborted" in statuses.values()
    assert set(statuses) == {"s0", "s1", "s2", "s3"}
    assert result.total_tokens_used >= 300  # at least the call that tipped it over 250
    assert result.total_tokens_used < 800  # ...but not all 4 scenarios' full 2 turns (== 800)
