#!/usr/bin/env python
"""`agent-eval` CLI: wires PRDs 1-4 together end to end (PRD 5).

    agent-eval run --suite suites/support.yaml --baseline baselines/v1.json

Exit codes: 0 pass, 1 gate failure, 2 run error (budget abort / crash).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from examples.reference_agent.agent import ReferenceAgent
from harness.cache import CacheMode
from harness.gate import check
from harness.metrics.aggregate import ScenarioResult, aggregate
from harness.metrics.efficiency import EfficiencyMetric, load_pricing
from harness.metrics.groundedness import GroundednessMetric
from harness.metrics.task_completion import TaskCompletionMetric
from harness.metrics.tool_call_accuracy import ToolCallAccuracyMetric
from harness.report.generator import ScenarioReportRow, generate
from harness.run import RunConfig, build_model_client, run_suite
from harness.suite import load_suite
from harness.tracing import instrument_model_client, setup_tracing


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _score_scenario(scenario, transcript, metrics: dict) -> tuple:
    task_completion = await metrics["task_completion"].score(transcript, scenario)
    tool_call_accuracy = await metrics["tool_call_accuracy"].score(transcript, scenario)
    efficiency = await metrics["efficiency"].score(transcript, scenario)
    groundedness = None
    if "groundedness" in metrics:
        groundedness = await metrics["groundedness"].score(transcript, scenario)
    return task_completion, tool_call_accuracy, efficiency, groundedness


async def _run(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    concurrency = args.concurrency or suite.manifest.concurrency
    token_budget = (
        args.token_budget if args.token_budget is not None else suite.manifest.token_budget
    )

    config = RunConfig(
        concurrency_limit=concurrency,
        total_token_budget=token_budget,
        default_simulator_model=suite.manifest.simulator_model,
        cache_mode=CacheMode(args.mode),
        cache_dir=args.cache_dir,
    )
    model_client, tracker = build_model_client(config)

    if args.trace_exporter != "none":
        setup_tracing(args.trace_exporter)
        instrument_model_client(model_client)

    agent = ReferenceAgent(model_client, model=suite.manifest.agent_model)

    run_result = await run_suite(suite.scenarios, agent, config, model_client, tracker)

    pricing = load_pricing(args.pricing)
    metrics: dict = {
        "task_completion": TaskCompletionMetric(),
        "tool_call_accuracy": ToolCallAccuracyMetric(),
        "efficiency": EfficiencyMetric(pricing),
    }
    if args.judge:
        metrics["groundedness"] = GroundednessMetric(model_client, suite.manifest.judge_model)

    scenario_by_id = {s.id: s for s in suite.scenarios}
    scoring_semaphore = asyncio.Semaphore(concurrency)

    async def _score_one(outcome):
        scenario = scenario_by_id[outcome.scenario_id]
        async with scoring_semaphore:
            try:
                scored = await _score_scenario(scenario, outcome.transcript, metrics)
            except Exception as exc:
                # A scoring failure (e.g. the judge model never returns a parseable verdict even
                # after its retry) shouldn't take down scoring for the rest of the suite -- it's
                # surfaced as a skipped scenario, not a crashed run.
                print(f"warning: scoring failed for {scenario.id!r}: {exc}", file=sys.stderr)
                return None
        return scenario, outcome.transcript, *scored

    completed_outcomes = [
        o for o in run_result.outcomes if o.status == "completed" and o.transcript is not None
    ]
    # Scoring runs concurrently (bounded by the same concurrency limit as scenario execution)
    # rather than one judge call at a time -- with N scenarios each needing a judge round-trip,
    # sequential scoring was the dominant cost of a full run.
    scored_results = await asyncio.gather(*(_score_one(o) for o in completed_outcomes))

    scenario_results: list[ScenarioResult] = []
    report_rows: list[ScenarioReportRow] = []

    for item in scored_results:
        if item is None:
            continue
        scenario, transcript, task_completion, tool_call_accuracy, efficiency, groundedness = item
        scenario_results.append(
            ScenarioResult(
                scenario_id=scenario.id,
                task_completion=task_completion,
                tool_call_accuracy=tool_call_accuracy,
                efficiency=efficiency,
                groundedness=groundedness,
            )
        )
        report_rows.append(
            ScenarioReportRow(
                scenario_id=scenario.id,
                intent=scenario.intent,
                task_completion=task_completion,
                tool_call_accuracy=tool_call_accuracy,
                efficiency=efficiency,
                groundedness=groundedness,
                transcript=transcript,
            )
        )

    suite_report = aggregate(scenario_results)

    baseline = None
    if args.baseline and Path(args.baseline).exists():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    thresholds = yaml.safe_load(Path(args.gate_thresholds).read_text(encoding="utf-8"))
    gate_result = check(suite_report, baseline or {}, thresholds)

    generate(
        suite_report,
        gate_result,
        baseline,
        report_rows,
        args.out,
        suite_name=suite.manifest.suite,
        model=suite.manifest.agent_model,
    )

    if args.update_baseline:
        if not args.baseline:
            print("error: --update-baseline requires --baseline PATH", file=sys.stderr)
            return 2
        if not scenario_results:
            # A baseline written from zero scored scenarios (e.g. a budget abort) would make
            # every future real run look like an infinite improvement against it -- worse than no
            # baseline at all, since the gate would never fire.
            print("error: --update-baseline refused, no scenarios were scored", file=sys.stderr)
            return 2
        new_baseline = {
            "suite": args.suite,
            "model": suite.manifest.agent_model,
            "created_at": _now_iso(),
            "metrics": {
                metric: (value if value is not None and math.isfinite(value) else None)
                for metric, value in {
                    "task_completion_rate": suite_report.task_completion_rate,
                    "tool_call_accuracy_mean": suite_report.tool_call_accuracy_mean,
                    "groundedness_mean": suite_report.groundedness_mean,
                    "cost_per_resolved_task": suite_report.cost_per_resolved_task,
                }.items()
            },
        }
        Path(args.baseline).write_text(json.dumps(new_baseline, indent=2) + "\n", encoding="utf-8")

    print(f"scenarios: {len(scenario_results)}/{len(suite.scenarios)} scored")
    print(f"task_completion_rate={suite_report.task_completion_rate:.3f}")
    print(f"tool_call_accuracy_mean={suite_report.tool_call_accuracy_mean:.3f}")
    if suite_report.groundedness_mean is not None:
        print(f"groundedness_mean={suite_report.groundedness_mean:.3f}")
    print(f"cost_per_resolved_task={suite_report.cost_per_resolved_task:.4f}")
    print(f"gate: {'PASS' if gate_result.passed else 'FAIL'}")
    for v in gate_result.violations:
        print(
            f"  VIOLATION {v.metric}: baseline={v.baseline:.4f} current={v.current:.4f} "
            f"delta={v.delta:.4f} threshold={v.threshold:.4f}"
        )

    if run_result.aborted:
        print("run aborted: token budget exceeded", file=sys.stderr)
        return 2
    return 0 if gate_result.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-eval")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a suite and score it")
    run_p.add_argument("--suite", required=True)
    run_p.add_argument("--baseline")
    run_p.add_argument("--mode", choices=["record", "replay", "live"], default="replay")
    run_p.add_argument("--concurrency", type=int, default=None)
    run_p.add_argument("--token-budget", type=int, default=None)
    run_p.add_argument("--out", default="results")
    run_p.add_argument("--update-baseline", action="store_true")
    run_p.add_argument("--trace-exporter", choices=["console", "otlp", "none"], default="none")
    run_p.add_argument("--pricing", default="config/model_pricing.yaml")
    run_p.add_argument("--gate-thresholds", default="config/gate_thresholds.yaml")
    run_p.add_argument("--cache-dir", default="cache")
    run_p.add_argument("--no-judge", dest="judge", action="store_false", default=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
