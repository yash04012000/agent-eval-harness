import json

from harness.judge.rubric import JudgeParseError, run_judge
from harness.metrics.groundedness import GroundednessMetric
from harness.model_client import ModelResponse, ToolCall
from harness.scenario import ExpectedOutcome, Persona, Scenario, UserSimulation
from harness.transcript import ToolCallRecord, Transcript, Turn


def _scenario() -> Scenario:
    return Scenario(
        id="s1",
        intent="order_status",
        description="check order status",
        opening_message="hi",
        user_simulation=UserSimulation(
            mode="simulated", persona=Persona(name="Alex", goal="find my order")
        ),
        expected_outcome=ExpectedOutcome(resolution="resolved"),
    )


def _transcript() -> Transcript:
    return Transcript(
        scenario_id="s1",
        end_reason="goal_achieved",
        turns=[
            Turn(
                agent_message="Your order has shipped and will arrive in 2 days.",
                tool_calls=[
                    ToolCallRecord(
                        id="c1",
                        name="lookup_order",
                        arguments={"order_id": "A100"},
                        response={"status": "shipped", "eta_days": 2},
                    )
                ],
            )
        ],
    )


def _verdict_response(verdict: str, rationale: str = "matches tool output") -> ModelResponse:
    return ModelResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="submit_groundedness_verdict",
                arguments={"verdict": verdict, "rationale": rationale, "claims": []},
                raw_arguments="{}",
            )
        ],
        prompt_tokens=20,
        completion_tokens=10,
        latency_ms=1.0,
        raw={},
    )


class _FakeJudgeClient:
    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        return self._responses.pop(0)


async def test_run_judge_parses_tool_call_verdict():
    client = _FakeJudgeClient([_verdict_response("grounded")])
    verdict = await run_judge(_transcript(), _scenario(), client, "judge-model")
    assert verdict.verdict == "grounded"
    assert verdict.rationale == "matches tool output"


async def test_run_judge_parses_free_text_json_fallback():
    response = ModelResponse(
        content=json.dumps({"verdict": "partial", "rationale": "unverifiable claim", "claims": []}),
        tool_calls=[],
        prompt_tokens=20,
        completion_tokens=10,
        latency_ms=1.0,
        raw={},
    )
    client = _FakeJudgeClient([response])
    verdict = await run_judge(_transcript(), _scenario(), client, "judge-model")
    assert verdict.verdict == "partial"


async def test_run_judge_retries_once_on_malformed_json_then_succeeds():
    bad_response = ModelResponse(
        content="not json at all", tool_calls=[], prompt_tokens=5, completion_tokens=5,
        latency_ms=1.0, raw={},
    )
    client = _FakeJudgeClient([bad_response, _verdict_response("not_grounded")])
    verdict = await run_judge(_transcript(), _scenario(), client, "judge-model")
    assert verdict.verdict == "not_grounded"
    assert len(client.calls) == 2


async def test_run_judge_drops_unparseable_stringified_claims_but_keeps_verdict():
    # Small local models sometimes stringify `claims` and get the escaping wrong -- the verdict
    # itself should still come through rather than failing the whole call over that one field.
    response = ModelResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="submit_groundedness_verdict",
                arguments={
                    "verdict": "grounded",
                    "rationale": "matches tool output",
                    "claims": '[{"claim": "shipped", "evidence": "says "shipped" here"}]',
                },
                raw_arguments="{}",
            )
        ],
        prompt_tokens=20,
        completion_tokens=10,
        latency_ms=1.0,
        raw={},
    )
    client = _FakeJudgeClient([response])
    verdict = await run_judge(_transcript(), _scenario(), client, "judge-model")
    assert verdict.verdict == "grounded"
    assert verdict.claims == []


async def test_run_judge_raises_after_exhausting_retry():
    bad_response = ModelResponse(
        content="still not json", tool_calls=[], prompt_tokens=5, completion_tokens=5,
        latency_ms=1.0, raw={},
    )
    client = _FakeJudgeClient([bad_response, bad_response])
    try:
        await run_judge(_transcript(), _scenario(), client, "judge-model")
        assert False, "expected JudgeParseError"
    except JudgeParseError:
        pass


async def test_groundedness_metric_maps_verdict_to_score():
    client = _FakeJudgeClient([_verdict_response("partial", "asserts an unverified fact")])
    metric = GroundednessMetric(client, "judge-model")

    result = await metric.score(_transcript(), _scenario())

    assert result.name == "groundedness"
    assert result.score == 0.5
    assert result.passed is True
    assert result.details["verdict"] == "partial"


async def test_groundedness_metric_not_grounded_fails():
    client = _FakeJudgeClient([_verdict_response("not_grounded", "contradicts tool output")])
    metric = GroundednessMetric(client, "judge-model")

    result = await metric.score(_transcript(), _scenario())

    assert result.score == 0.0
    assert result.passed is False
