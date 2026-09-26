#!/usr/bin/env python
"""Builds PRD 4's judge-validation set.

Runs the full suite through the reference agent with 2-3 simulated-user seeds per scenario,
producing 50+ distinct transcripts from ~20-25 suite scenarios -- rather than inflating the demo
suite past what's needed for good scenario coverage. Recorded once in `record` mode (real model
calls, via `--mode record`); every downstream step (judge, human labeling, agreement report) then
runs against this fixed, cached set forever.

Usage: python scripts/build_validation_set.py suites/support.yaml [--seeds 3] [--mode record]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from examples.reference_agent.agent import ReferenceAgent
from harness.cache import CachedModelClient, CacheMode
from harness.model_client import LiteLLMModelClient
from harness.orchestrator import run_scenario
from harness.suite import load_suite


async def _build(suite_path: str, seeds: int, mode: CacheMode, cache_dir: str, out_dir: str) -> int:
    suite = load_suite(suite_path)
    model_client = CachedModelClient(LiteLLMModelClient(), cache_dir=cache_dir, mode=mode)
    agent = ReferenceAgent(model_client, model=suite.manifest.simulator_model)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_dir = Path(suite_path).parent
    count = 0

    for scenario_path, scenario in zip(suite.manifest.scenario_paths, suite.scenarios, strict=True):
        seed_range = range(seeds) if scenario.user_simulation.mode == "simulated" else range(1)
        for seed in seed_range:
            use_seed = seed if scenario.user_simulation.mode == "simulated" else None
            transcript = await run_scenario(
                scenario, agent, model_client, suite.manifest.simulator_model, seed=use_seed
            )
            transcript_id = f"{scenario.id}__seed{use_seed if use_seed is not None else 0}"
            record = {
                "transcript_id": transcript_id,
                "scenario_id": scenario.id,
                "scenario_path": str(base_dir / scenario_path),
                "seed": use_seed,
                "transcript": json.loads(transcript.model_dump_json()),
            }
            (out / f"{transcript_id}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
            count += 1
            print(f"wrote {transcript_id} ({transcript.end_reason}, {len(transcript.turns)} turns)")

    print(f"\n{count} validation transcripts written to {out}/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--mode", choices=["record", "replay"], default="record")
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--out", default="data/validation_transcripts")
    args = parser.parse_args()
    return asyncio.run(
        _build(args.suite, args.seeds, CacheMode(args.mode), args.cache_dir, args.out)
    )


if __name__ == "__main__":
    sys.exit(main())
