"""Metric protocol every scorer implements (PRD 3), including the judge-backed one in PRD 4."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from harness.scenario import Scenario
from harness.transcript import Transcript


class MetricResult(BaseModel):
    name: str
    score: float
    passed: bool | None
    details: dict = Field(default_factory=dict)


class Metric(Protocol):
    name: str

    def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult: ...
