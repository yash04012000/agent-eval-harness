"""Resolves a model's tool call against a scenario's data-only mock table (PRD 2)."""

from __future__ import annotations

import json
import time

import jsonschema

from harness.model_client import ToolCall
from harness.scenario import ToolDef
from harness.tool_hooks import get_hook
from harness.transcript import ToolCallRecord


class ToolMockExecutor:
    def __init__(self, tools: list[ToolDef], scenario_id: str):
        self._by_name = {tool.name: tool for tool in tools}
        self._scenario_id = scenario_id

    def execute(self, tool_call: ToolCall) -> ToolCallRecord:
        start = time.perf_counter()

        def record(**kwargs) -> ToolCallRecord:
            return ToolCallRecord(
                id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments,
                latency_ms=(time.perf_counter() - start) * 1000,
                **kwargs,
            )

        tool = self._by_name.get(tool_call.name)
        if tool is None:
            return record(error="unknown_tool")

        try:
            jsonschema.validate(instance=tool_call.arguments, schema=tool.parameters)
        except jsonschema.ValidationError:
            return record(error="invalid_args")

        hook = get_hook(self._scenario_id, tool_call.name)
        if hook is not None:
            return record(response=hook(tool_call.arguments))

        response = self._match_response(tool, tool_call.arguments)
        if response is None:
            return record(error="no_mock_response")
        return record(response=response)

    @staticmethod
    def _match_response(tool: ToolDef, arguments: dict) -> dict | None:
        for key, response in tool.responses.items():
            try:
                parsed_key = json.loads(key)
            except json.JSONDecodeError:
                continue
            if parsed_key == arguments:
                return response
        return tool.default_response
