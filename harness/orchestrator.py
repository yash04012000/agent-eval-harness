"""Drives one scenario from opening message to `Transcript` (PRD 2)."""

from __future__ import annotations

from typing import Any

from harness.agent_adapter import AgentAdapter
from harness.model_client import ModelClient
from harness.scenario import Scenario
from harness.simulated_user import ScriptedUser, SimulatedUser, SimulatedUserProtocol
from harness.tool_executor import ToolMockExecutor
from harness.transcript import EndReason, Transcript, Turn


def _build_user(
    scenario: Scenario, model_client: ModelClient, default_simulator_model: str
) -> SimulatedUserProtocol:
    user_simulation = scenario.user_simulation
    if user_simulation.mode == "scripted":
        return ScriptedUser(user_simulation.script or [])
    return SimulatedUser(
        persona=user_simulation.persona,
        model=user_simulation.simulator_model or default_simulator_model,
        max_turns=user_simulation.max_turns,
        model_client=model_client,
    )


async def run_scenario(
    scenario: Scenario,
    agent: AgentAdapter,
    model_client: ModelClient,
    default_simulator_model: str = "gpt-4o-mini",
) -> Transcript:
    messages: list[dict[str, Any]] = [{"role": "user", "content": scenario.opening_message}]
    user = _build_user(scenario, model_client, default_simulator_model)
    executor = ToolMockExecutor(scenario.tools, scenario.id)
    turns: list[Turn] = []
    end_reason: EndReason = "max_turns"

    for _ in range(scenario.user_simulation.max_turns):
        turn_result = await agent.take_turn(messages, scenario.tools, executor)
        messages.append({"role": "assistant", "content": turn_result.assistant_message})
        turns.append(
            Turn(agent_message=turn_result.assistant_message, tool_calls=turn_result.tool_calls)
        )

        user_turn = await user.next(messages)
        if user_turn.ended:
            end_reason = user_turn.end_reason or "gave_up"  # type: ignore[assignment]
            break
        messages.append({"role": "user", "content": user_turn.message})

    return Transcript(
        scenario_id=scenario.id, turns=turns, end_reason=end_reason, messages=messages
    )
