"""The agent-under-test is a black box, per turn (PRD 2).

The harness doesn't assume anything about an agent's internal architecture. It only assumes: given
the full message history and a `ToolMockExecutor` bound to the current scenario, the agent returns
a final assistant message plus every tool call it made getting there.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from harness.scenario import ToolDef
from harness.tool_executor import ToolMockExecutor
from harness.transcript import ToolCallRecord


class AgentTurnResult(BaseModel):
    assistant_message: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AgentAdapter(Protocol):
    async def take_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDef],
        executor: ToolMockExecutor,
    ) -> AgentTurnResult: ...
