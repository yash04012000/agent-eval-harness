#!/usr/bin/env python
"""Load every scenario YAML under `suites/` and fail loudly on the first invalid one.

Usage: python scripts/validate_scenarios.py [suites_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from harness.scenario import load_scenario
from harness.suite import load_suite


def _is_suite_manifest(path: Path) -> bool:
    """Suite manifests (e.g. `suites/support.yaml`) have a top-level `scenarios` list; scenario
    files don't -- this is what distinguishes the two when both live under `suites/`."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return isinstance(data, dict) and "scenarios" in data


def main(suites_dir: str = "suites") -> int:
    root = Path(suites_dir)
    paths = sorted(root.rglob("*.yaml"))
    if not paths:
        print(f"no scenario files found under {root}/")
        return 1

    errors = 0
    for path in paths:
        if _is_suite_manifest(path):
            try:
                suite = load_suite(path)
            except (ValidationError, FileNotFoundError) as exc:
                errors += 1
                print(f"INVALID  {path}\n{exc}\n")
                continue
            print(f"ok       {path}  (suite manifest, {len(suite.scenarios)} scenarios)")
            continue
        try:
            scenario = load_scenario(path)
        except ValidationError as exc:
            errors += 1
            print(f"INVALID  {path}\n{exc}\n")
            continue
        print(f"ok       {path}  ({scenario.id})")

    if errors:
        print(f"\n{errors}/{len(paths)} scenario file(s) failed validation")
        return 1

    print(f"\nall {len(paths)} scenario file(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
