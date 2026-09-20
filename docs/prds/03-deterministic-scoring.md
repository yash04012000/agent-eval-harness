# PRD 3 — Deterministic scoring: task completion, tool-call accuracy, efficiency

Status: Draft · Depends on: PRD 1, 2 · Blocks: PRD 5 (gate needs these numbers)

## Summary

Three of the four required metrics need no judge model at all — they're checks against structured
data already sitting in the `Transcript` (tool calls made, messages sent, tokens spent). Scoring
these deterministically means they're free to run, exactly reproducible, and a solid floor under
the one metric (groundedness, PRD 4) that does need a judge.

## Goals

- `Metric` protocol every scorer implements, so the run driver and report generator treat all
  metrics uniformly (including the judge-backed one added in PRD 4).
- `TaskCompletionMetric`: did the transcript satisfy `expected_outcome`.
- `ToolCallAccuracyMetric`: right tool, right arguments, no hallucinated tools.
- `EfficiencyMetric`: turns, tokens, and cost per scenario, plus a suite-level cost-per-resolved-task
  rollup.
- Suite-level aggregation (rates and means) in the shape PRD 5's baseline/gate and report need.

## Non-goals

- Groundedness (PRD 4 — needs a judge, needs validation, gets its own PRD).
- Rendering anything (PRD 5 owns the report; this PRD returns structured `MetricResult`s).

## Design

```python
# harness/metrics/base.py
class MetricResult(BaseModel):
    name: str
    score: float                  # 0.0-1.0, always — even for count-based metrics, normalized
    passed: bool | None           # None when the metric has no pass/fail notion on its own
    details: dict                 # sub-checks, for the report to explain *why*

class Metric(Protocol):
    name: str
    def score(self, transcript: Transcript, scenario: Scenario) -> MetricResult: ...
```

### Task completion

```python
# harness/metrics/task_completion.py
def score(transcript, scenario) -> MetricResult:
    outcome = scenario.expected_outcome
    called = {tc.name for tc in all_tool_calls(transcript)}
    checks = {
        "required_tool_calls": outcome.required_tool_calls <= called,          # subset check
        "forbidden_tool_calls": not (set(outcome.forbidden_tool_calls) & called),
        "must_mention": all(s.lower() in final_message(transcript).lower() for s in outcome.must_mention),
        "must_not_mention": not any(s.lower() in final_message(transcript).lower() for s in outcome.must_not_mention),
        "resolution": infer_resolution(transcript) == outcome.resolution,
    }
    passed = all(checks.values())
    return MetricResult(name="task_completion", score=1.0 if passed else 0.0,
                         passed=passed, details=checks)
```

`infer_resolution` reads `transcript.end_reason` (`goal_achieved` → `resolved`,
`gave_up`/`max_turns` → not resolved unless the scenario explicitly expects `escalated` and an
escalation tool was called, etc.) — the exact mapping is a small, explicit table, not a heuristic,
so a report reader can see precisely why a scenario was marked failed. Task completion is
binary (0.0/1.0) per scenario; the suite-level number is the pass rate.

### Tool-call accuracy

Per problem statement wording — "right tool, right arguments, no hallucinated tools" — scored
per call, then averaged:

```python
# harness/metrics/tool_call_accuracy.py
def classify(call: ToolCallRecord, scenario: Scenario) -> Literal["correct", "hallucinated", "invalid_args"]:
    if call.error == "unknown_tool":
        return "hallucinated"
    if call.error == "invalid_args":
        return "invalid_args"
    return "correct"

def score(transcript, scenario) -> MetricResult:
    calls = all_tool_calls(transcript)
    if not calls:
        return MetricResult(name="tool_call_accuracy", score=1.0, passed=None,
                             details={"note": "no tool calls made"})
    classified = [classify(c, scenario) for c in calls]
    correct = classified.count("correct")
    return MetricResult(name="tool_call_accuracy", score=correct / len(classified),
                         passed=correct == len(classified),
                         details={"calls": len(classified), "hallucinated": classified.count("hallucinated"),
                                   "invalid_args": classified.count("invalid_args")})
```

Decision to flag: this scores *precision* (of the calls made, how many were legitimate) — it does
not separately check *recall* (whether all necessary calls were made), because that's already
covered by `required_tool_calls` in task completion. Keeping the two metrics non-overlapping
means a report reader isn't double-penalized for the same mistake under two different numbers.

A scenario with zero tool calls scores 1.0 (vacuously — nothing wrong happened) but `passed=None`
so the report can visually distinguish "used tools correctly" from "used no tools," which matters
for a reader auditing whether the metric is meaningful for that scenario.

### Efficiency

```python
# harness/metrics/efficiency.py
class EfficiencyDetail(BaseModel):
    turns: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

def score(transcript, scenario, pricing: dict[str, ModelPricing]) -> MetricResult:
    detail = compute(transcript, pricing)   # sums per-call token/latency records on the transcript
    # normalized against scenario-level or config-level target turns/cost so score is 0-1;
    # e.g. score = clamp(target_turns / actual_turns, 0, 1) — a scenario resolved in fewer turns
    # than the target scores 1.0, one that ran long scores proportionally lower.
    ...
    return MetricResult(name="efficiency", score=..., passed=None, details=detail.model_dump())
```

Suite-level rollup (not per-scenario) is where "cost per resolved task" — the number the resume
line and the regression gate actually care about — is computed:

```python
# harness/metrics/aggregate.py
def cost_per_resolved_task(results: list[ScenarioResult]) -> float:
    resolved = [r for r in results if r.task_completion.passed]
    total_cost = sum(r.efficiency.details["cost_usd"] for r in results)   # all attempts, not just resolved
    return total_cost / len(resolved) if resolved else float("inf")
```

Model pricing lives in a committed config file so cost is computed consistently and reviewably:

```yaml
# config/model_pricing.yaml
gpt-4o-mini: {prompt_per_1k: 0.00015, completion_per_1k: 0.0006}
ollama/llama3.1: {prompt_per_1k: 0.0, completion_per_1k: 0.0}
```

### Aggregation for the gate and report

```python
# harness/metrics/aggregate.py
class SuiteReport(BaseModel):
    scenario_results: list[ScenarioResult]     # per-scenario MetricResults for all metrics
    task_completion_rate: float
    tool_call_accuracy_mean: float
    groundedness_mean: float | None            # filled in once PRD 4 lands; None until then
    cost_per_resolved_task: float
    total_tokens: int
    total_cost_usd: float
```

This is the exact shape PRD 5 diffs against a baseline file and renders into a report — defining
it now (even with `groundedness_mean` as a placeholder) means PRD 4 slots in without reshaping
anything downstream.

### File/module layout

```
harness/metrics/
  base.py
  task_completion.py
  tool_call_accuracy.py
  efficiency.py
  aggregate.py
config/
  model_pricing.yaml
tests/
  test_task_completion.py     # one test per checks{} branch, plus a fully-passing fixture
  test_tool_call_accuracy.py  # hallucinated, invalid_args, correct, zero-calls
  test_efficiency.py           # cost math against a fixed pricing fixture, turns normalization
  test_aggregate.py             # cost_per_resolved_task with 0 resolved (inf), mixed pass/fail
```

## Testing plan

Every metric is a pure function over a hand-built `Transcript` fixture — no model calls, no
network, so this whole PRD's test suite runs in milliseconds and is what CI actually executes on
every PR regardless of cache/replay mode. Fixtures cover each classification branch explicitly
(hallucinated call, invalid-args call, missing required call, forbidden call present, etc.) so a
future change to the scoring logic that silently stops catching one of these fails a test, not a
report months later.

## Acceptance criteria this PRD unblocks

"4 metrics implemented" — 3 of 4 (task completion, tool-call accuracy, efficiency); groundedness
is PRD 4. Feeds the "cost per resolved task" figure the efficiency requirement names explicitly.

## Open questions for review

1. Efficiency's 0-1 normalization needs a `target_turns` / `target_cost` reference point per
   scenario or per suite — is that worth adding to the PRD 1 schema now (an optional field on
   `Scenario`), or is a single suite-wide default good enough for the demo?
2. Should `tool_call_accuracy` penalize a call that's valid (real tool, valid args) but not one of
   the response-table entries the scenario author anticipated — i.e., a call to a real tool with
   plausible-but-untested arguments? Current design treats it as `correct`; the alternative
   (`unanticipated`) would make scenario authoring more brittle (every plausible argument
   combination needs a mock entry) in exchange for slightly stricter scoring.
