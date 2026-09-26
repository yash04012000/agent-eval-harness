"""Regression gate: fails a run when a metric drops past a configured threshold (PRD 5).

A metric absent from the baseline (first run, or a brand-new metric added later) is skipped
rather than treated as a violation -- the gate only compares what it has a prior number for.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from harness.metrics.aggregate import SuiteReport

_EPSILON = 1e-9  # float-precision slack so a delta exactly at the threshold reliably passes

_GATED_METRICS = (
    "task_completion_rate",
    "tool_call_accuracy_mean",
    "groundedness_mean",
    "cost_per_resolved_task",
)


class Violation(BaseModel):
    metric: str
    baseline: float
    current: float
    delta: float
    threshold: float


class GateResult(BaseModel):
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def _current_metrics(report: SuiteReport) -> dict[str, float | None]:
    return {
        "task_completion_rate": report.task_completion_rate,
        "tool_call_accuracy_mean": report.tool_call_accuracy_mean,
        "groundedness_mean": report.groundedness_mean,
        "cost_per_resolved_task": report.cost_per_resolved_task,
    }


def check(current: SuiteReport, baseline: dict[str, Any], thresholds: dict[str, Any]) -> GateResult:
    baseline_metrics = baseline.get("metrics", {})
    current_metrics = _current_metrics(current)
    violations: list[Violation] = []
    skipped: list[str] = []

    for metric in _GATED_METRICS:
        current_value = current_metrics[metric]
        baseline_value = baseline_metrics.get(metric)
        if baseline_value is None or current_value is None:
            skipped.append(metric)
            continue
        threshold = thresholds.get(metric, {})

        if "max_drop" in threshold:
            delta = baseline_value - current_value  # positive delta == got worse
            if delta > threshold["max_drop"] + _EPSILON:
                violations.append(
                    Violation(
                        metric=metric,
                        baseline=baseline_value,
                        current=current_value,
                        delta=delta,
                        threshold=threshold["max_drop"],
                    )
                )
        elif "max_increase_pct" in threshold:
            if baseline_value == 0:
                continue  # nothing to compute a percentage increase against
            delta = (current_value - baseline_value) / baseline_value
            if delta > threshold["max_increase_pct"] + _EPSILON:
                violations.append(
                    Violation(
                        metric=metric,
                        baseline=baseline_value,
                        current=current_value,
                        delta=delta,
                        threshold=threshold["max_increase_pct"],
                    )
                )

    return GateResult(passed=not violations, violations=violations, skipped=skipped)
