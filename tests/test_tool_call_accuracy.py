from harness.metrics.tool_call_accuracy import ToolCallAccuracyMetric, classify
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


def _transcript(tool_calls) -> Transcript:
    return Transcript(
        scenario_id="s1",
        end_reason="goal_achieved",
        turns=[Turn(agent_message="done", tool_calls=tool_calls)],
    )


def test_classify_hallucinated():
    call = ToolCallRecord(id="c1", name="made_up_tool", arguments={}, error="unknown_tool")
    assert classify(call) == "hallucinated"


def test_classify_invalid_args():
    call = ToolCallRecord(id="c1", name="lookup_order", arguments={}, error="invalid_args")
    assert classify(call) == "invalid_args"


def test_classify_correct():
    call = ToolCallRecord(id="c1", name="lookup_order", arguments={"order_id": "A100"})
    assert classify(call) == "correct"


def test_classify_no_mock_response_counts_as_correct():
    call = ToolCallRecord(
        id="c1", name="lookup_order", arguments={"order_id": "Z999"}, error="no_mock_response"
    )
    assert classify(call) == "correct"


def test_zero_calls_scores_one_but_passed_is_none():
    result = ToolCallAccuracyMetric().score(_transcript([]), _scenario())
    assert result.score == 1.0
    assert result.passed is None


def test_all_correct_calls_pass():
    calls = [ToolCallRecord(id="c1", name="lookup_order", arguments={"order_id": "A100"})]
    result = ToolCallAccuracyMetric().score(_transcript(calls), _scenario())
    assert result.score == 1.0
    assert result.passed is True


def test_mixed_calls_average_and_fail():
    calls = [
        ToolCallRecord(id="c1", name="lookup_order", arguments={"order_id": "A100"}),
        ToolCallRecord(id="c2", name="made_up_tool", arguments={}, error="unknown_tool"),
    ]
    result = ToolCallAccuracyMetric().score(_transcript(calls), _scenario())
    assert result.score == 0.5
    assert result.passed is False
    assert result.details == {"calls": 2, "hallucinated": 1, "invalid_args": 0}
