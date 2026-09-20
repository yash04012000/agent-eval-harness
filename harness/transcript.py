"""What a scenario run produces: the artifact every metric (PRD 3, 4) scores (PRD 2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EndReason = Literal["goal_achieved", "gave_up", "max_turns"]


class ToolCallRecord(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    response: dict[str, Any] | None = None
    error: Literal["unknown_tool", "invalid_args", "no_mock_response"] | None = None
    latency_ms: float = 0.0


class Turn(BaseModel):
    agent_message: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class Transcript(BaseModel):
    scenario_id: str
    turns: list[Turn] = Field(default_factory=list)
    end_reason: EndReason
    messages: list[dict[str, Any]] = Field(default_factory=list)


def all_tool_calls(transcript: Transcript) -> list[ToolCallRecord]:
    return [tc for turn in transcript.turns for tc in turn.tool_calls]


def final_message(transcript: Transcript) -> str:
    return transcript.turns[-1].agent_message if transcript.turns else ""
