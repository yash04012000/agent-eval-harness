"""Scenario schema: the YAML contract every suite is written against (PRD 1)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema.validators import Draft7Validator
from pydantic import BaseModel, Field, model_validator


class Difficulty(StrEnum):
    NORMAL = "normal"
    VAGUE = "vague"
    CHANGES_MIND = "changes_mind"
    WRONG_IDS = "wrong_ids"
    ADVERSARIAL = "adversarial"


class Persona(BaseModel):
    name: str
    goal: str
    traits: list[str] = Field(default_factory=list)
    difficulty: Difficulty = Difficulty.NORMAL


class ScriptedTurn(BaseModel):
    user: str


class UserSimulation(BaseModel):
    mode: Literal["scripted", "simulated"]
    persona: Persona | None = None
    script: list[ScriptedTurn] | None = None
    max_turns: int = 12
    simulator_model: str | None = None

    @model_validator(mode="after")
    def _require_fields_for_mode(self) -> UserSimulation:
        if self.mode == "simulated" and self.persona is None:
            raise ValueError("user_simulation.persona is required when mode is 'simulated'")
        if self.mode == "scripted" and not self.script:
            raise ValueError("user_simulation.script is required when mode is 'scripted'")
        return self


class ToolDef(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    responses: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_response: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _parameters_must_be_a_valid_json_schema(self) -> ToolDef:
        try:
            Draft7Validator.check_schema(self.parameters)
        except Exception as exc:
            raise ValueError(
                f"tool '{self.name}': parameters is not a valid JSON Schema: {exc}"
            ) from exc
        return self


class ExpectedOutcome(BaseModel):
    resolution: Literal["resolved", "escalated", "refused"]
    required_tool_calls: list[str] = Field(default_factory=list)
    forbidden_tool_calls: list[str] = Field(default_factory=list)
    must_mention: list[str] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str
    intent: str
    description: str
    adversarial: bool = False
    opening_message: str
    user_simulation: UserSimulation
    tools: list[ToolDef] = Field(default_factory=list)
    expected_outcome: ExpectedOutcome
    token_budget: int | None = None


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a single scenario YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Scenario.model_validate(data)
