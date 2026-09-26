"""The judge's structured verdict (PRD 4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    evidence: str | None = None


class JudgeVerdict(BaseModel):
    verdict: Literal["grounded", "partial", "not_grounded"]
    rationale: str
    claims: list[ClaimVerdict] = Field(default_factory=list)
