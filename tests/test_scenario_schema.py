from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.scenario import Scenario, load_scenario

SMOKE_SCENARIO = Path(__file__).parent.parent / "suites" / "_schema_smoke.yaml"


def test_loads_valid_scenario():
    scenario = load_scenario(SMOKE_SCENARIO)
    assert scenario.id == "schema_smoke"
    assert scenario.user_simulation.mode == "scripted"
    assert scenario.tools[0].name == "lookup_order"
    assert scenario.expected_outcome.required_tool_calls == ["lookup_order"]


def _base_scenario_dict(**overrides):
    base = {
        "id": "t1",
        "intent": "test",
        "description": "test scenario",
        "opening_message": "hi",
        "user_simulation": {"mode": "scripted", "script": [{"user": "hello"}]},
        "expected_outcome": {"resolution": "resolved"},
    }
    base.update(overrides)
    return base


def test_simulated_mode_without_persona_raises():
    data = _base_scenario_dict(
        user_simulation={"mode": "simulated", "max_turns": 5}
    )
    with pytest.raises(ValidationError, match="persona is required"):
        Scenario.model_validate(data)


def test_scripted_mode_without_script_raises():
    data = _base_scenario_dict(user_simulation={"mode": "scripted"})
    with pytest.raises(ValidationError, match="script is required"):
        Scenario.model_validate(data)


def test_malformed_tool_json_schema_raises():
    data = _base_scenario_dict(
        tools=[
            {
                "name": "broken_tool",
                "description": "has an invalid JSON Schema",
                "parameters": {"type": "not-a-real-json-schema-type"},
            }
        ]
    )
    with pytest.raises(ValidationError, match="not a valid JSON Schema"):
        Scenario.model_validate(data)


def test_valid_simulated_scenario_parses():
    data = _base_scenario_dict(
        user_simulation={
            "mode": "simulated",
            "persona": {"name": "Alex", "goal": "get a refund", "difficulty": "vague"},
        }
    )
    scenario = Scenario.model_validate(data)
    assert scenario.user_simulation.persona.difficulty == "vague"
