"""Suite-level aggregation: the shape PRD 5's gate and report consume (PRD 3)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from harness.metrics.base import MetricResult


class ScenarioResult(BaseModel):
    scenario_id: str
    task_completion: MetricResult
    tool_call_accuracy: MetricResult
    efficiency: MetricResult
    groundedness: MetricResult | None = None


class SuiteReport(BaseModel):
    scenario_results: list[ScenarioResult] = Field(default_factory=list)
    task_completion_rate: float
    tool_call_accuracy_mean: float
    groundedness_mean: float | None = None
    cost_per_resolved_task: float
    total_tokens: int
    total_cost_usd: float


def cost_per_resolved_task(results: list[ScenarioResult]) -> float:
    resolved = [r for r in results if r.task_completion.passed]
    total_cost = sum(r.efficiency.details["cost_usd"] for r in results)
    return total_cost / len(resolved) if resolved else float("inf")


def aggregate(results: list[ScenarioResult]) -> SuiteReport:
    if not results:
        return SuiteReport(
            task_completion_rate=0.0,
            tool_call_accuracy_mean=0.0,
            cost_per_resolved_task=float("inf"),
            total_tokens=0,
            total_cost_usd=0.0,
        )

    task_completion_rate = sum(1 for r in results if r.task_completion.passed) / len(results)
    tool_call_accuracy_mean = sum(r.tool_call_accuracy.score for r in results) / len(results)

    groundedness_scores = [r.groundedness.score for r in results if r.groundedness is not None]
    groundedness_mean = (
        sum(groundedness_scores) / len(groundedness_scores) if groundedness_scores else None
    )

    total_tokens = sum(
        r.efficiency.details["prompt_tokens"] + r.efficiency.details["completion_tokens"]
        for r in results
    )
    total_cost_usd = sum(r.efficiency.details["cost_usd"] for r in results)

    return SuiteReport(
        scenario_results=results,
        task_completion_rate=task_completion_rate,
        tool_call_accuracy_mean=tool_call_accuracy_mean,
        groundedness_mean=groundedness_mean,
        cost_per_resolved_task=cost_per_resolved_task(results),
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
    )
