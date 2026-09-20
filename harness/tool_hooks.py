"""Escape hatch for tool mocks that need state across calls within one scenario (PRD 1).

Scenario YAML keeps tool mocks as plain data (a response lookup table). The rare scenario that
needs a second call to see the effect of a first one registers a hook here instead -- kept out of
scenario files so loading a scenario never means executing arbitrary code from YAML.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Hook = Callable[[dict[str, Any]], dict[str, Any]]

_hooks: dict[tuple[str, str], Hook] = {}


def register_hook(scenario_id: str, tool_name: str, hook: Hook) -> None:
    _hooks[(scenario_id, tool_name)] = hook


def get_hook(scenario_id: str, tool_name: str) -> Hook | None:
    return _hooks.get((scenario_id, tool_name))


def clear_hooks() -> None:
    """Test-only: reset the registry between test cases."""
    _hooks.clear()
