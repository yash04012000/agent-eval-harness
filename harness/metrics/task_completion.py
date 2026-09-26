"""Task completion: did the transcript satisfy `scenario.expected_outcome` (PRD 3)."""

from __future__ import annotations

from harness.metrics.base import MetricResult
from harness.scenario import Scenario
from harness.transcript import Transcript, all_tool_calls, final_message


def infer_resolution(transcript: Transcript, scenario: Scenario) -> str | None:
    """Map `end_reason` (plus which tools were called) to a `resolution` value.

    An explicit small table, not a heuristic, so a report reader can see precisely why a
    scenario was marked failed:
      - `goal_achieved`          -> "resolved"
      - `max_turns`              -> None (ran out of budget, not a deliberate outcome)
      - `gave_up`                -> "escalated" if the scenario expects escalation and every
                                     `required_tool_calls` entry was called; "refused" if the
                                     scenario expects a refusal and no tools were called at all;
                                     otherwise None
    """
    if transcript.end_reason == "goal_achieved":
        return "resolved"
    if transcript.end_reason == "max_turns":
        return None

    outcome = scenario.expected_outcome
    called = {tc.name for tc in all_tool_calls(transcript) if tc.error is None}
    if outcome.resolution == "escalated" and outcome.required_tool_calls:
        if set(outcome.required_tool_calls) <= called:
            return "escalated"
    if outcome.resolution == "refused" and not called:
        return "refused"
    return None


class TaskCompletionMetric:
    name = "task_completion"

    async def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult:
        outcome = scenario.expected_outcome
        called = {tc.name for tc in all_tool_calls(transcript) if tc.error is None}
        message = final_message(transcript).lower()
        checks = {
            "required_tool_calls": set(outcome.required_tool_calls) <= called,
            "forbidden_tool_calls": not (set(outcome.forbidden_tool_calls) & called),
            "must_mention": all(s.lower() in message for s in outcome.must_mention),
            "must_not_mention": not any(s.lower() in message for s in outcome.must_not_mention),
            "resolution": infer_resolution(transcript, scenario) == outcome.resolution,
        }
        passed = all(checks.values())
        return MetricResult(
            name=self.name, score=1.0 if passed else 0.0, passed=passed, details=checks
        )
