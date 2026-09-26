# Design notes

## Problem

Teams shipping LLM agents can't tell whether a prompt change, a model swap, or a new tool made
things better or worse without eyeballing transcripts by hand. This harness turns agent quality
into numbers a CI pipeline can gate on: scenarios defined in YAML, run against the agent through a
simulated multi-turn user, scored on four dimensions, failing the build when a score regresses
past a threshold.

The constraints that make this non-trivial:

- **No human in the loop, but conversations still need to be adversarial, vague, and multi-turn.**
  A scripted fixture can't cover "customer changes their mind" or "customer gives the wrong order
  ID" -- an LLM has to play the user.
- **The one metric that most needs judgment (groundedness) can't be scored deterministically**,
  but an unvalidated LLM judge is worthless -- it needs its own accuracy measurement against
  humans, not just a rubric and a hope.
- **CI has to run for free, on every PR, including forks**, which rules out live model calls in
  the default path entirely.
- **Model-agnostic by requirement** -- a reader without API credits still needs to be able to run
  this, which is why every model call in this repo, including the agent-under-test, the simulated
  user, and the judge, goes through a local Ollama model (`llama3.1:8b`) by default rather than a
  hosted API.

## Architecture

```
scenario YAML --> orchestrator --> Transcript --> {deterministic metrics, judge} --> gate --> report
                     ^      \                                                          |
              simulated user  agent-under-test (ReferenceAgent + tool mocks)      baseline diff
```

Walking one scenario end to end (`billing_large_refund_escalation`):

1. `harness.scenario.load_scenario` parses and validates the YAML against the Pydantic schema
   (persona, tools with mocked responses, expected outcome).
2. `harness.orchestrator.run_scenario` drives the loop: the opening message goes to the
   agent-under-test (`examples.reference_agent.ReferenceAgent`); its tool calls are resolved by
   `ToolMockExecutor` against the scenario's data-only response table; the simulated user (an LLM
   playing "Sam Okafor, disputing a $120 charge") replies; repeat until the user ends the
   conversation or `max_turns` is hit. The result is a `Transcript`: every turn, every tool call,
   token counts, and how it ended.
3. Every model call -- agent, user, judge -- goes through the same `CachedModelClient`
   (`harness/cache.py`), so a CI run replays a committed cache and never touches a real model.
4. The `Transcript` is scored by all four `Metric` implementations: `TaskCompletionMetric` checks
   the transcript against `expected_outcome` (did it escalate a >$50 refund instead of issuing it
   directly); `ToolCallAccuracyMetric` checks the tool calls actually made were real, valid calls;
   `EfficiencyMetric` sums tokens/turns and prices them from `config/model_pricing.yaml`;
   `GroundednessMetric` asks a judge model whether the agent's final message is supported by what
   the tools returned.
5. `harness.metrics.aggregate.aggregate` rolls all `ScenarioResult`s into one `SuiteReport`.
   `harness.gate.check` diffs it against `baselines/v1.json` per `config/gate_thresholds.yaml`.
   `harness.report.generator.generate` renders the same data into `results/report.md` and
   `results/report.html`.
6. The CLI (`agent-eval run --suite suites/support.yaml --baseline baselines/v1.json`) exits `0`
   on pass, `1` on a gate violation, `2` on a run error (budget abort or crash) -- so CI can act on
   it directly.

## Options considered and rejected

- **LiteLLM vs. httpx**: LiteLLM, so the same `ModelClient` interface works unmodified against
  OpenAI-compatible hosted endpoints and local Ollama models -- writing a provider-specific client
  would defeat the model-agnostic requirement.
- **Data-only tool mocks vs. arbitrary hook code in scenario YAML**: data-only (a response lookup
  table keyed by canonicalized arguments), with a small `harness/tool_hooks.py` escape hatch
  registered in Python for the rare case that needs state across calls. Loading a scenario should
  never mean executing arbitrary code from a YAML file a contributor submitted in a PR.
- **Categorical judge rubric (grounded/partial/not_grounded) + Cohen's kappa vs. a raw numeric
  judge score**: categorical, because a human labeler can apply "grounded or not" consistently in
  a way they can't apply "rate this 0-100," and kappa is designed to compare exactly this kind of
  categorical agreement while correcting for chance agreement that a skewed label distribution
  would otherwise inflate.
- **Judge model choice**: same local model (`llama3.1:8b`) as the agent-under-test, not a
  separate, stronger model. The PRD's own recommendation was a different/stronger judge to avoid
  sharing the agent's blind spots; the honest tradeoff made here instead is cost and
  reproducibility with zero API keys required, at the cost of a judge that shares the same model's
  weaknesses (nested-JSON formatting slips, weaker reasoning) as what it's judging. This is called
  out explicitly in Failure modes and Limitations rather than hidden.
- **Jaeger vs. a print-based trace viewer**: Jaeger, via `docker-compose.yml`, dev-only -- OTLP
  export is a few lines of SDK config and gives a real waterfall view of concurrent scenarios,
  which a flat log can't.
- **argparse vs. a CLI framework (typer/click)**: argparse. One `run` subcommand with ~10 flags
  doesn't need a framework's help-text niceties badly enough to justify a new dependency.
- **cost-per-resolved-task vs. raw cost as the efficiency headline**: cost-per-resolved-task,
  because raw cost alone doesn't distinguish "expensive but reliable" from "cheap but never
  finishes the job" -- dividing by resolved tasks (not attempted tasks) is what a team actually
  budgets against.
- **Pluggable `--agent-module` CLI flag vs. bundling the reference agent directly**: bundled. The
  `AgentAdapter` protocol (`harness/agent_adapter.py`) is agent-agnostic by design, but this repo
  has no external agent-under-test to plug in -- adding loader machinery nothing here would use
  would be speculative generality, not a real requirement.

## Failure modes

- **Judge disagreement.** `scripts/judge_validation_report.py` generates
  `results/judge_validation_report.md` (kappa, confusion matrix, every disagreement with both
  verdicts) from `data/human_labels.csv` and the cached judge -- as of this writing that
  validation study hasn't been run yet (see README's Limitations), so there is no kappa figure to
  cite. A judge below the 0.6 "substantial agreement" bar (Landis & Koch) would mean groundedness
  scores should be read as a rough signal, not a precise one, once that number exists.
- **Local judge model formatting slips.** `llama3.1:8b`, run through a forced tool call, sometimes
  stringifies the nested `claims` array in its own verdict, and that string is occasionally
  invalid JSON (mismatched quote-escaping once an "evidence" value itself contains quoted tool
  output). `harness/judge/rubric.py` degrades gracefully -- an unparseable `claims` field is
  dropped (empty list) rather than failing the whole verdict, since `verdict` and `rationale` are
  what groundedness is actually scored on. A verdict that fails to parse at all after one retry is
  surfaced as a per-scenario scoring failure (logged, skipped) rather than crashing the run.
- **Simulated user output types.** The same small-model class of issue shows up in the simulated
  user: a forced tool call sometimes returns `"ended": "false"` (a string) instead of a JSON
  boolean. `harness/simulated_user.py` passes the raw value through Pydantic's own bool coercion
  rather than Python's `bool()` builtin (which would treat the non-empty string `"false"` as
  truthy) -- a one-line fix, but the kind of thing that would otherwise silently truncate every
  simulated conversation to one turn.
- **Cache staleness.** The cache is keyed by a hash of the exact request (model, messages, tools,
  temperature) -- if a scenario's prompt or tool schema changes, its cache entries simply don't
  match anymore and a `replay`-mode run raises `CacheMiss` with an explicit message telling the
  operator to re-run in `record` mode. It fails loudly, not silently with stale data.
  `refresh-cache.yml` is the deliberate, manually-triggered path that updates the cache; nothing
  updates it as a side effect of an ordinary run.
- **Budget abort mid-run.** `TokenBudgetTracker` raises once the shared token budget is exceeded;
  `run_suite` cancels whatever's still in flight and marks it `aborted`, and the CLI still
  generates a report for whatever did complete (partial information beats none when debugging why
  a run got expensive) but exits `2`, distinct from a gate failure's `1`.
- **A simulated user that won't end the conversation.** `max_turns` (set per scenario, default 12)
  is the hard stop; a scenario that hits it scores `task_completion=0` (no `resolved`/`escalated`/
  `refused` outcome was reached) rather than hanging the run.

## What changes at 10,000 scenarios

- **Flat-file cache → needs an index or a real KV store.** `CacheStore` does a filesystem lookup
  per hash today; fine for a few hundred entries, not for tens of thousands across every scenario
  x seed x model combination.
- **The judge becomes the dominant cost.** 10,000 judge calls, not 50 -- exhaustive judging stops
  being affordable even with a free local model (wall-clock, not just API cost). Sampling a subset
  per run, not judging every scenario every time, becomes necessary.
- **The fixed 50-conversation hand-label set stops being representative.** It would need
  stratified re-sampling across intents and difficulty levels as the scenario suite grows, rather
  than staying frozen at the original 50.
- **Concurrency becomes limited by provider rate limits, not local resources.** `run_suite`'s
  semaphore assumes the bottleneck is the operator's own machine/budget; at 10,000 scenarios
  against a hosted provider, backoff and sharding across API keys matters more than the
  concurrency limit itself.
- **Report generation needs pagination/summarization**, not one flat HTML page -- the current
  report template renders every failing scenario's full transcript inline, which doesn't scale
  past a page a reviewer can actually read.

## Limitations

- Tools are mocked, not real integrations -- the harness validates agent behavior against a
  scripted response table, not against a live backend.
- The judge is validated on conversations from one reference agent on one local model family; the
  kappa figure is evidence about *this* judge on *this* agent, not a general claim about judge
  reliability across arbitrary agents or models.
- The hand-label sample (50 conversations) is small enough that the kappa estimate has real
  sampling uncertainty -- treat it as a point estimate, not a precise reliability figure.
- Every model in this demo (agent, simulated user, judge) is the same small local model
  (`llama3.1:8b`) for zero-cost reproducibility. That means the judge shares the agent's own
  blind spots rather than checking it from an independent, stronger vantage point -- a real
  deployment gating a production agent should use a separate, stronger judge model.
