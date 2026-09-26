"""Suite manifest: lists scenario files + suite-level config (PRD 5/6)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from harness.scenario import Scenario, load_scenario


class SuiteManifest(BaseModel):
    suite: str
    scenario_paths: list[str] = Field(default_factory=list)
    concurrency: int = 4
    token_budget: int | None = None
    simulator_model: str = "gpt-4o-mini"
    judge_model: str = "gpt-4o-mini"
    # The model the bundled `examples.reference_agent.ReferenceAgent` (the agent-under-test the
    # CLI runs) uses. The harness's `AgentAdapter` protocol is otherwise agent-agnostic, but this
    # repo's CLI always evaluates its own reference agent, so its model belongs in suite config
    # alongside the simulator/judge models rather than as a separate wiring mechanism.
    agent_model: str = "gpt-4o-mini"


class Suite(BaseModel):
    manifest: SuiteManifest
    scenarios: list[Scenario]


def load_suite(path: str | Path) -> Suite:
    """Load a suite manifest and every scenario it lists, relative to the manifest's directory."""
    manifest_path = Path(path)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    scenario_paths = data.pop("scenarios", [])
    manifest = SuiteManifest(scenario_paths=scenario_paths, **data)
    base_dir = manifest_path.parent
    scenarios = [load_scenario(base_dir / p) for p in scenario_paths]
    return Suite(manifest=manifest, scenarios=scenarios)
