"""Tool-call accuracy: right tool, right arguments, no hallucinated tools (PRD 3).

Scores *precision* of the calls actually made -- whether all necessary calls were made (recall)
is already covered by `required_tool_calls` in task completion. Keeping the two metrics
non-overlapping means a report reader isn't double-penalized for the same mistake twice.
"""

from __future__ import annotations

from typing import Literal

from harness.metrics.base import MetricResult
from harness.scenario import Scenario
from harness.transcript import ToolCallRecord, Transcript, all_tool_calls

Classification = Literal["correct", "hallucinated", "invalid_args"]


def classify(call: ToolCallRecord) -> Classification:
    if call.error == "unknown_tool":
        return "hallucinated"
    if call.error == "invalid_args":
        return "invalid_args"
    # `no_mock_response` (a real tool, valid args, just no matching mock entry) and a clean call
    # both count as "correct" -- see PRD 3 open question 2.
    return "correct"


class ToolCallAccuracyMetric:
    name = "tool_call_accuracy"

    async def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult:
        calls = all_tool_calls(transcript)
        if not calls:
            return MetricResult(
                name=self.name, score=1.0, passed=None, details={"note": "no tool calls made"}
            )
        classified = [classify(c) for c in calls]
        correct = classified.count("correct")
        return MetricResult(
            name=self.name,
            score=correct / len(classified),
            passed=correct == len(classified),
            details={
                "calls": len(classified),
                "hallucinated": classified.count("hallucinated"),
                "invalid_args": classified.count("invalid_args"),
            },
        )
