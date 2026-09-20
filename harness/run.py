"""Run-level driver: concurrency limit + shared token budget across a whole suite (PRD 2).

The agent-under-test is a pre-built, opaque `AgentAdapter` -- the harness can't reach inside it to
make its model calls count against the run's budget. Instead, `build_model_client` constructs the
one cached/budget-tracked `ModelClient` up front; the caller uses that *same instance* to build
their agent (so the agent's calls count) and passes it back into `run_suite` (so the simulated
user's calls count against the identical tracker).
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from harness.agent_adapter import AgentAdapter
from harness.budget import BudgetExceeded, TokenBudgetTracker
from harness.cache import CachedModelClient, CacheMode
from harness.model_client import LiteLLMModelClient, ModelClient
from harness.orchestrator import run_scenario
from harness.scenario import Scenario
from harness.transcript import Transcript


class RunConfig(BaseModel):
    concurrency_limit: int = 4
    total_token_budget: int | None = None
    default_simulator_model: str = "gpt-4o-mini"
    cache_mode: CacheMode = CacheMode.REPLAY
    cache_dir: str = "cache"


class ScenarioRunOutcome(BaseModel):
    scenario_id: str
    status: Literal["completed", "aborted", "error"] = "completed"
    transcript: Transcript | None = None
    error: str | None = None


class RunResult(BaseModel):
    outcomes: list[ScenarioRunOutcome] = Field(default_factory=list)
    aborted: bool = False
    total_tokens_used: int = 0


def build_model_client(
    config: RunConfig, inner_client: ModelClient | None = None
) -> tuple[ModelClient, TokenBudgetTracker]:
    """Build the one cached, budget-tracked client every model call in the run should share.

    `inner_client` overrides the real LiteLLM client -- tests inject a fake here.
    """
    tracker = TokenBudgetTracker(config.total_token_budget)
    model_client = CachedModelClient(
        inner_client or LiteLLMModelClient(),
        cache_dir=config.cache_dir,
        mode=config.cache_mode,
        on_usage=tracker.add,
    )
    return model_client, tracker


async def run_suite(
    scenarios: list[Scenario],
    agent: AgentAdapter,
    config: RunConfig,
    model_client: ModelClient,
    tracker: TokenBudgetTracker,
) -> RunResult:
    """Run every scenario, bounded by `config.concurrency_limit`.

    `agent` must have been built with the same `model_client` returned by `build_model_client`
    (or a compatible one sharing `tracker`), or the agent's own model calls won't count against
    the budget this function enforces.
    """
    semaphore = asyncio.Semaphore(config.concurrency_limit)

    async def run_one(scenario: Scenario) -> ScenarioRunOutcome:
        async with semaphore:
            transcript = await run_scenario(
                scenario, agent, model_client, config.default_simulator_model
            )
            return ScenarioRunOutcome(
                scenario_id=scenario.id, transcript=transcript, status="completed"
            )

    tasks = {scenario.id: asyncio.create_task(run_one(scenario)) for scenario in scenarios}
    task_to_id = {task: scenario_id for scenario_id, task in tasks.items()}
    outcomes: dict[str, ScenarioRunOutcome] = {}
    aborted = False
    pending = set(tasks.values())

    # asyncio.wait(..., FIRST_EXCEPTION) reacts to a budget blowout as soon as it happens, rather
    # than only noticing once we happen to await that specific scenario's task -- minimizing (not
    # eliminating -- other already-runnable tasks can still race ahead in the same event-loop
    # tick) how much extra work starts after the budget is already over.
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            scenario_id = task_to_id[task]
            exc = task.exception()
            if exc is None:
                outcomes[scenario_id] = task.result()
            elif isinstance(exc, BudgetExceeded):
                aborted = True
            else:
                outcomes[scenario_id] = ScenarioRunOutcome(
                    scenario_id=scenario_id, status="error", error=str(exc)
                )
        if aborted:
            break

    if aborted:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for scenario_id in tasks:
            if scenario_id not in outcomes:
                outcomes[scenario_id] = ScenarioRunOutcome(
                    scenario_id=scenario_id, status="aborted"
                )

    return RunResult(
        outcomes=[outcomes[scenario.id] for scenario in scenarios],
        aborted=aborted,
        total_tokens_used=tracker.used,
    )
