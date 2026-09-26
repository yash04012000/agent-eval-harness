"""Groundedness: the one metric that needs judgment, not just structured-data checks (PRD 4)."""

from __future__ import annotations

from harness.judge.rubric import run_judge
from harness.metrics.base import MetricResult
from harness.model_client import ModelClient
from harness.scenario import Scenario
from harness.transcript import Transcript

_VERDICT_SCORE = {"grounded": 1.0, "partial": 0.5, "not_grounded": 0.0}


class GroundednessMetric:
    name = "groundedness"

    def __init__(self, judge_client: ModelClient, judge_model: str):
        self._client = judge_client
        self._model = judge_model

    async def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult:
        verdict = await run_judge(transcript, scenario, self._client, self._model)
        return MetricResult(
            name=self.name,
            score=_VERDICT_SCORE[verdict.verdict],
            passed=verdict.verdict != "not_grounded",
            details={
                "verdict": verdict.verdict,
                "rationale": verdict.rationale,
                "claims": [c.model_dump() for c in verdict.claims],
            },
        )
