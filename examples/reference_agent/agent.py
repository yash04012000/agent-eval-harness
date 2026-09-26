"""Minimal single-loop tool-calling agent (PRD 2) -- the demo suite's agent-under-test."""

from __future__ import annotations

import json
from typing import Any

from examples.reference_agent.prompts import DEFAULT_SYSTEM_PROMPT
from harness.agent_adapter import AgentTurnResult
from harness.model_client import ModelClient
from harness.scenario import ToolDef
from harness.tool_executor import ToolMockExecutor
from harness.transcript import ToolCallRecord


def _to_openai_tools(tools: list[ToolDef]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


class ReferenceAgent:
    """Implements `harness.agent_adapter.AgentAdapter`.

    Calls the model, executes any tool calls it makes via the scenario's `ToolMockExecutor` in a
    bounded internal loop, and re-prompts with the results until the model stops calling tools.
    """

    def __init__(
        self,
        model_client: ModelClient,
        model: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_iterations: int = 5,
    ):
        self._client = model_client
        self._model = model
        self._system_prompt = system_prompt
        self._max_tool_iterations = max_tool_iterations

    async def take_turn(
        self, messages: list[dict[str, Any]], tools: list[ToolDef], executor: ToolMockExecutor
    ) -> AgentTurnResult:
        working: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            *messages,
        ]
        tool_schema = _to_openai_tools(tools)
        collected: list[ToolCallRecord] = []
        prompt_tokens = 0
        completion_tokens = 0

        for _ in range(self._max_tool_iterations):
            response = await self._client.complete(
                model=self._model, messages=working, tools=tool_schema, temperature=0.0
            )
            prompt_tokens += response.prompt_tokens
            completion_tokens += response.completion_tokens
            if not response.tool_calls:
                return AgentTurnResult(
                    assistant_message=response.content or "",
                    tool_calls=collected,
                    model=self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

            working.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.raw_arguments},
                        }
                        for tc in response.tool_calls
                    ],
                }
            )
            for tool_call in response.tool_calls:
                record = executor.execute(tool_call)
                collected.append(record)
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            record.response
                            if record.response is not None
                            else {"error": record.error}
                        ),
                    }
                )

        # Exhausted the internal loop without a final message -- surface what was collected.
        return AgentTurnResult(
            assistant_message="",
            tool_calls=collected,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
