# PRD 5 — Regression gates, tracing, reporting, CLI

Status: Draft · Depends on: PRD 1-4 · Blocks: PRD 6 (content needs the CLI to run)

## Summary

Integration layer: everything upstream produces numbers and transcripts; this PRD is what a human
or a CI job actually invokes, what decides pass/fail against a baseline, what makes the run
inspectable after the fact (traces), and what turns a `SuiteReport` into something a PR reviewer
reads in thirty seconds (the HTML/MD report).

## Goals

- `agent-eval run --suite ... --baseline ... [--mode] [--concurrency] [--token-budget] [--out]`
  CLI entry point wiring PRDs 1-4 together end to end.
- Baseline file format + `RegressionGate` that fails the run when a metric drops past a threshold.
- OpenTelemetry spans around every model call and tool call, viewable locally.
- HTML and Markdown report generator: per-scenario pass/fail, failing transcripts inline, baseline
  diff.
- Exit codes CI can act on: `0` pass, `1` gate failure, `2` run error (budget abort / crash).

## Non-goals

- Writing the scenarios or the GH Actions workflow that calls this CLI on every PR (PRD 6) — this
  PRD makes the CLI correct and testable against the existing schema-smoke fixture; PRD 6 is what
  points real CI traffic at it.

## Design

### Baseline format and regression gate

```json
// baselines/v1.json
{
  "suite": "suites/support.yaml",
  "model": "gpt-4o-mini",
  "created_at": "2026-09-01T00:00:00Z",
  "metrics": {
    "task_completion_rate": 0.85,
    "tool_call_accuracy_mean": 0.92,
    "groundedness_mean": 0.80,
    "cost_per_resolved_task": 0.014
  }
}
```

```yaml
# config/gate_thresholds.yaml
task_completion_rate:      { max_drop: 0.05 }     # absolute pp drop allowed
tool_call_accuracy_mean:   { max_drop: 0.05 }
groundedness_mean:         { max_drop: 0.05 }
cost_per_resolved_task:    { max_increase_pct: 0.20 }
```

```python
# harness/gate.py
class Violation(BaseModel):
    metric: str
    baseline: float
    current: float
    delta: float
    threshold: float

class GateResult(BaseModel):
    passed: bool
    violations: list[Violation]

def check(current: SuiteReport, baseline: dict, thresholds: dict) -> GateResult: ...
```

A metric absent from the baseline (first run, or a brand-new metric added later) is skipped with a
note in the report rather than treated as a violation — the gate only compares what it has a prior
number for. `agent-eval run --update-baseline` (explicit flag, never implicit) writes the current
`SuiteReport`'s metrics as the new baseline — this is a deliberate, reviewable action (the diff
shows up in the PR that changes `baselines/v1.json`), not something a passing run does silently.

### Tracing

```python
# harness/tracing.py
def setup_tracing(exporter: Literal["console", "otlp"]) -> TracerProvider: ...

# spans, nested: run -> scenario -> turn -> {model_call | tool_call}
# attributes on model_call: model, prompt_tokens, completion_tokens, latency_ms, cache_hit
# attributes on tool_call: tool_name, error (if any), latency_ms
```

Instrumentation wraps the two seams that already exist as single functions from PRD 1/2 —
`ModelClient.complete` and `ToolMockExecutor.execute` — via a decorator, so no call site in PRDs
1-4 needs to change; tracing is added around them, not threaded through them.

Local viewing: `docker-compose.yml` (dev-only, not required for CI) runs Jaeger all-in-one;
`--trace-exporter otlp` points at it, UI at `localhost:16686`. This is what the README screenshot
comes from. CI itself uses `--trace-exporter console` (or omits tracing) since there's no Jaeger
service in the Actions runner and traces aren't needed to decide pass/fail — they're for human
debugging of a specific run, not part of the gate.

### Report generator

```python
# harness/report/generator.py
def generate(report: SuiteReport, gate: GateResult, baseline: dict | None, out_dir: Path) -> None:
    # renders templates/report.html.j2 and templates/report.md.j2 with:
    #   - summary table: metric, baseline, current, delta, within-threshold?
    #   - per-scenario table: id, intent, task_completion / tool_call_accuracy / groundedness, pass/fail
    #   - failing scenarios expanded inline: full transcript, tool calls with args/responses,
    #     judge rationale if groundedness failed
    ...
```

Markdown output is what a PR comment or a terminal-based reviewer wants; HTML is what the README
screenshot and a browser-based reviewer want. Both render from the same `SuiteReport` + `GateResult`
so they can never disagree with each other.

### CLI

```python
# cli.py
def main():
    parser = argparse.ArgumentParser(prog="agent-eval")
    sub = parser.add_subparsers(required=True)
    run = sub.add_parser("run")
    run.add_argument("--suite", required=True)
    run.add_argument("--baseline")
    run.add_argument("--mode", choices=["record", "replay", "live"], default="replay")
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--token-budget", type=int, default=None)
    run.add_argument("--out", default="results/")
    run.add_argument("--update-baseline", action="store_true")
    run.add_argument("--trace-exporter", choices=["console", "otlp", "none"], default="none")
    ...
```

Decision: stdlib `argparse`, not a new dependency (`typer`/`click`) — the problem statement's stack
list doesn't call one out, and a single `run` subcommand with ~7 flags doesn't need a framework's
help-text niceties badly enough to justify the extra pin. Exposed via `console_scripts` in
`pyproject.toml` so `agent-eval run ...` works after `pip install -e .`, matching the CLI shape the
problem statement specifies verbatim.

### File/module layout

```
harness/
  gate.py
  tracing.py
  report/
    generator.py
    templates/report.html.j2
    templates/report.md.j2
cli.py
config/
  gate_thresholds.yaml
docker-compose.yml          # jaeger, dev-only
pyproject.toml               # console_scripts entry point
tests/
  test_gate.py                # pass, fail-at-threshold-boundary, missing-metric-in-baseline
  test_report_generator.py    # renders both templates from a fixture SuiteReport without error
  test_cli_smoke.py            # subprocess run against suites/_schema_smoke.yaml in replay mode,
                                 # asserts exit code and that results/report.{html,md} exist
```

## Testing plan

Gate thresholds are tested at the exact boundary (delta equal to `max_drop` passes; one unit past
it fails) since off-by-one threshold bugs are exactly the kind of thing that silently lets a
regression through. The report generator test only checks the templates render without a Jinja2
error against a representative fixture (a mix of passing/failing scenarios, at least one
groundedness failure with a judge rationale) — not exact HTML output, which would make the test
brittle against copy changes. The CLI smoke test is the one full-stack test in the repo: it
actually invokes `agent-eval run` as a subprocess against the tiny schema-smoke suite in replay
mode, so a wiring mistake between any two PRDs surfaces here even if every unit test upstream
passes.

## Acceptance criteria this PRD unblocks

"Regression gates," "Reports," "CLI," and "Traces viewable locally, screenshot in README"
(the screenshot itself is PRD 6, but this PRD is what makes a trace exist to screenshot).

## Open questions for review

1. Threshold shape: absolute point-drop (`max_drop: 0.05`) for rate metrics vs. percentage
   increase (`max_increase_pct`) for cost — consistent enough, or should everything use one shape
   for simplicity even if it reads slightly oddly for cost?
2. Should a budget-abort (`RunResult.aborted`) produce a report at all, or just the distinct exit
   code 2 with a short message? Leaning: still produce a report for whatever did complete — partial
   information is more useful than none when debugging why a run got expensive.
3. `--trace-exporter none` as CI default vs. always running `console` exporter so trace data at
   least lands in CI logs even without Jaeger — minor, but decides whether CI logs get noisier.
