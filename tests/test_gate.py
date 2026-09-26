from harness.gate import check
from harness.metrics.aggregate import SuiteReport

THRESHOLDS = {
    "task_completion_rate": {"max_drop": 0.05},
    "tool_call_accuracy_mean": {"max_drop": 0.05},
    "groundedness_mean": {"max_drop": 0.05},
    "cost_per_resolved_task": {"max_increase_pct": 0.20},
}

BASELINE = {
    "metrics": {
        "task_completion_rate": 0.85,
        "tool_call_accuracy_mean": 0.92,
        "groundedness_mean": 0.80,
        "cost_per_resolved_task": 0.014,
    }
}


def _report(**overrides) -> SuiteReport:
    defaults = dict(
        task_completion_rate=0.85,
        tool_call_accuracy_mean=0.92,
        groundedness_mean=0.80,
        cost_per_resolved_task=0.014,
        total_tokens=1000,
        total_cost_usd=0.5,
    )
    defaults.update(overrides)
    return SuiteReport(**defaults)


def test_identical_to_baseline_passes():
    result = check(_report(), BASELINE, THRESHOLDS)
    assert result.passed is True
    assert result.violations == []


def test_drop_exactly_at_threshold_passes():
    result = check(_report(task_completion_rate=0.85 - 0.05), BASELINE, THRESHOLDS)
    assert result.passed is True


def test_drop_one_unit_past_threshold_fails():
    result = check(_report(task_completion_rate=0.85 - 0.05 - 0.001), BASELINE, THRESHOLDS)
    assert result.passed is False
    assert result.violations[0].metric == "task_completion_rate"


def test_improvement_never_violates():
    result = check(_report(task_completion_rate=0.99), BASELINE, THRESHOLDS)
    assert result.passed is True


def test_cost_increase_within_pct_passes():
    result = check(_report(cost_per_resolved_task=0.014 * 1.20), BASELINE, THRESHOLDS)
    assert result.passed is True


def test_cost_increase_past_pct_fails():
    result = check(_report(cost_per_resolved_task=0.014 * 1.21), BASELINE, THRESHOLDS)
    assert result.passed is False
    assert result.violations[0].metric == "cost_per_resolved_task"


def test_metric_missing_from_baseline_is_skipped_not_a_violation():
    baseline = {"metrics": {"task_completion_rate": 0.85}}
    result = check(_report(), baseline, THRESHOLDS)
    assert result.passed is True
    assert "tool_call_accuracy_mean" in result.skipped
    assert "groundedness_mean" in result.skipped
    assert "cost_per_resolved_task" in result.skipped


def test_none_groundedness_is_skipped():
    baseline = {"metrics": {"groundedness_mean": 0.80}}
    result = check(_report(groundedness_mean=None), baseline, THRESHOLDS)
    assert "groundedness_mean" in result.skipped
    assert result.passed is True
