# agent-eval-harness

Turns LLM agent quality into numbers a CI pipeline can gate on: scenarios defined in YAML, run
against an agent through a simulated multi-turn user, scored on four dimensions, failing the build
when a score regresses.

## Results

**Status: the full 22-scenario demo suite (`suites/support.yaml`) is written and passes schema
validation, but has not yet been fully run against a live model** -- that's the next step, not
finished work being hidden. The numbers below are real, reproducible-today results from
`suites/support_small.yaml`, a 4-scenario subset (one plain lookup, one refund-under-limit, one
refund-over-limit requiring escalation, one prompt-injection adversarial test) that *has* been
fully recorded, cached, and committed, using a local `llama3.1:8b` model for the agent, the
simulated user, and the judge -- zero API keys required to reproduce:

| Metric | Value |
|---|---|
| Task completion rate | 0.0% (0/4) |
| Tool-call accuracy (mean) | 100% |
| Groundedness (mean) | 0.625 |
| Cost per resolved task | n/a (0 resolved) |

Zero task completions is a real, honestly-reported result, not a bug: with this small local model,
every failure is distinct and instructive -- one scenario the agent hallucinated a refund request
that was never made, one it completed every required step correctly but never cleanly closed the
conversation, one it violated the stated $50-refund-escalation policy, and the adversarial one it
partially fell for a prompt-injected instruction embedded in a tool's output (issuing an unrequested
refund) before partially self-correcting. See [`results/report.md`](results/report.md) for the full
transcripts behind each of these.

**Not yet done**: the 50-conversation judge-validation study (Cohen's kappa against human labels)
that PRD 4 defines -- the judge, the labeling script, and the agreement-report generator are all
built and unit-tested (`harness/judge/`, `scripts/label_conversations.py`,
`scripts/judge_validation_report.py`), but no conversations have been generated or labeled yet.
`docs/prds/00-overview.md` tracks exactly what's outstanding.

## Quickstart (30 seconds, no API keys)

```bash
git clone <this-repo>
cd agent-eval-harness
pip install -e .
agent-eval run --suite suites/support_small.yaml --baseline baselines/v1.json
```

This runs entirely against the committed cache (`replay` mode, the default) -- no model calls, no
API key, same result every time. Open `results/report.html` for the full report. Swap in
`suites/support.yaml` once its full cache is recorded (see Results, above) for all 22 scenarios.

To run against a live model instead (needs [Ollama](https://ollama.com) running locally with
`llama3.1:8b` pulled, or set `OPENAI_API_KEY` and point a suite's `*_model` fields at a hosted
model):

```bash
agent-eval run --suite suites/support_small.yaml --mode record
```

## Architecture

```
scenario YAML --> orchestrator --> Transcript --> {deterministic metrics, judge} --> gate --> report
                     ^      \                                                          |
              simulated user  agent-under-test (ReferenceAgent + tool mocks)      baseline diff
```

- **Scenarios** (`suites/support/*.yaml`): a persona, an opening message, a scripted or
  LLM-simulated multi-turn user, mocked tools, and an expected outcome. 22 scenarios across 4
  intents (billing, returns, order status, account access), 2 of them adversarial.
- **Simulated user**: an LLM plays the customer -- vague, gives wrong IDs, changes their mind
  mid-conversation, or (in the 2 adversarial scenarios) actively tries to get the agent to break
  policy.
- **Metrics** (`harness/metrics/`): task completion and tool-call accuracy are deterministic
  checks against the transcript; efficiency sums tokens/turns/cost; groundedness is judged by an
  LLM reading the transcript against a rubric (validation study pending, see Results above).
- **Gate** (`harness/gate.py`): diffs the current run against `baselines/v1.json`; a regression
  past `config/gate_thresholds.yaml`'s limits fails the build.
- **Tracing**: every model call and tool call gets an OpenTelemetry span
  (`model`/`prompt_tokens`/`completion_tokens`/`cache_hit` and `tool_name`/`error`/`latency_ms`
  respectively). `docker-compose.yml` runs a local Jaeger for viewing them.

Full design writeup, including options considered and rejected, failure modes actually hit while
building this, and what breaks at 10,000 scenarios: [DESIGN.md](DESIGN.md).

## Reproducing the numbers

```bash
# replay the committed cache (default, no model calls):
agent-eval run --suite suites/support_small.yaml --baseline baselines/v1.json

# re-record against a live model (needs Ollama running locally with llama3.1:8b pulled):
agent-eval run --suite suites/support_small.yaml --mode record --update-baseline

# once the validation set + human labels exist, regenerate the judge agreement report:
python scripts/judge_validation_report.py
```

CI (`.github/workflows/ci.yml`) runs the `eval-gate` job in `replay` mode on every PR, currently
scoped to `suites/support_small.yaml` (the subset with committed cache coverage) -- zero secrets
needed, so it runs on forks too. `refresh-cache.yml` is a manually-triggered workflow for refreshing
cache/baseline against a *hosted* model (it takes a `suite` input pointed at a manifest configured
for whatever model the provided API key can reach); this repo's own default suites point at a local
Ollama model instead, since GitHub-hosted runners have no GPU to run one at reasonable speed.

## Limitations

- Tools are mocked against a scripted response table, not real integrations.
- The full 22-scenario suite hasn't been live-recorded yet -- current results are from the
  4-scenario `support_small.yaml` subset only (see Results, above).
- The judge validation study (50 hand-labeled conversations, Cohen's kappa) hasn't been run yet --
  the groundedness metric works and is scored, but its reliability is currently unmeasured.
- Every model in this demo (agent, simulated user, judge) is the same local model
  (`llama3.1:8b`) for zero-cost reproducibility, so the judge would share the agent's own blind
  spots rather than checking it from an independent vantage point once validation does happen. A
  production deployment should use a separate, stronger judge model.

See [DESIGN.md](DESIGN.md) for the full discussion.
