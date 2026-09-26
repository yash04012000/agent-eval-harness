from harness.metrics.aggregate import ScenarioResult, aggregate, cost_per_resolved_task
from harness.metrics.base import MetricResult


def _result(scenario_id, *, task_passed, tool_score=1.0, cost_usd=1.0, tokens=(100, 50)):
    return ScenarioResult(
        scenario_id=scenario_id,
        task_completion=MetricResult(
            name="task_completion",
            score=1.0 if task_passed else 0.0,
            passed=task_passed,
            details={},
        ),
        tool_call_accuracy=MetricResult(
            name="tool_call_accuracy", score=tool_score, passed=None, details={}
        ),
        efficiency=MetricResult(
            name="efficiency",
            score=1.0,
            passed=None,
            details={
                "turns": 1,
                "prompt_tokens": tokens[0],
                "completion_tokens": tokens[1],
                "cost_usd": cost_usd,
            },
        ),
    )


def test_cost_per_resolved_task_with_zero_resolved_is_inf():
    results = [_result("s1", task_passed=False, cost_usd=2.0)]
    assert cost_per_resolved_task(results) == float("inf")


def test_cost_per_resolved_task_divides_total_cost_by_resolved_count():
    results = [
        _result("s1", task_passed=True, cost_usd=1.0),
        _result("s2", task_passed=False, cost_usd=3.0),
    ]
    # total cost includes all attempts (4.0), divided by 1 resolved scenario
    assert cost_per_resolved_task(results) == 4.0


def test_aggregate_empty_suite():
    report = aggregate([])
    assert report.task_completion_rate == 0.0
    assert report.tool_call_accuracy_mean == 0.0
    assert report.cost_per_resolved_task == float("inf")
    assert report.groundedness_mean is None


def test_aggregate_mixed_pass_fail():
    results = [
        _result("s1", task_passed=True, tool_score=1.0, cost_usd=1.0, tokens=(100, 50)),
        _result("s2", task_passed=False, tool_score=0.5, cost_usd=2.0, tokens=(200, 100)),
    ]
    report = aggregate(results)

    assert report.task_completion_rate == 0.5
    assert report.tool_call_accuracy_mean == 0.75
    assert report.groundedness_mean is None
    assert report.total_tokens == 450
    assert report.total_cost_usd == 3.0
    assert report.cost_per_resolved_task == 3.0  # total cost / 1 resolved
    assert len(report.scenario_results) == 2
