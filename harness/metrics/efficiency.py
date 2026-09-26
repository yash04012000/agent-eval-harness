"""Efficiency: turns, tokens, and cost per scenario (PRD 3).

Score is normalized against a single suite-wide `target_turns` rather than a per-scenario field
on the schema -- good enough for the demo's scope without reopening PRD 1 (see PRD 3 open
question 1).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from harness.metrics.base import MetricResult
from harness.scenario import Scenario
from harness.transcript import Transcript


class ModelPricing(BaseModel):
    prompt_per_1k: float
    completion_per_1k: float


class EfficiencyDetail(BaseModel):
    turns: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


def load_pricing(path: str | Path) -> dict[str, ModelPricing]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {name: ModelPricing.model_validate(fields) for name, fields in data.items()}


def compute(transcript: Transcript, pricing: dict[str, ModelPricing]) -> EfficiencyDetail:
    prompt_tokens = sum(turn.prompt_tokens for turn in transcript.turns)
    completion_tokens = sum(turn.completion_tokens for turn in transcript.turns)
    cost_usd = 0.0
    for turn in transcript.turns:
        model_pricing = pricing.get(turn.model) if turn.model else None
        if model_pricing is None:
            continue
        cost_usd += (turn.prompt_tokens / 1000) * model_pricing.prompt_per_1k
        cost_usd += (turn.completion_tokens / 1000) * model_pricing.completion_per_1k
    return EfficiencyDetail(
        turns=len(transcript.turns),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


class EfficiencyMetric:
    name = "efficiency"

    def __init__(self, pricing: dict[str, ModelPricing], target_turns: int = 6):
        self._pricing = pricing
        self._target_turns = target_turns

    async def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult:
        detail = compute(transcript, self._pricing)
        actual_turns = detail.turns or 1
        score = min(self._target_turns / actual_turns, 1.0)
        return MetricResult(name=self.name, score=score, passed=None, details=detail.model_dump())
