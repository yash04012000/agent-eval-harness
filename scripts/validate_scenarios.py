#!/usr/bin/env python
"""Load every scenario YAML under `suites/` and fail loudly on the first invalid one.

Usage: python scripts/validate_scenarios.py [suites_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from harness.scenario import load_scenario


def main(suites_dir: str = "suites") -> int:
    root = Path(suites_dir)
    paths = sorted(root.rglob("*.yaml"))
    if not paths:
        print(f"no scenario files found under {root}/")
        return 1

    errors = 0
    for path in paths:
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
