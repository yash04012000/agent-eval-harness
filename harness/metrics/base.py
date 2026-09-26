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
    """Every scorer -- including the judge-backed groundedness metric (PRD 4) -- is async, so the
    run driver can `await` all four uniformly without special-casing the one that makes a model
    call.
    """

    name: str

    async def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult: ...
