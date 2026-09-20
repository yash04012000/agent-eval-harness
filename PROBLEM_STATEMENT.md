# P1: Agent Evaluation Harness

Repo: `agent-eval-harness` | Effort: 3-4 weeks | Unlocks: Senior AI, GenAI, Applied AI at labs

## The problem

Teams ship LLM agents and then cannot tell whether a prompt change, a model swap or a new tool made
things better or worse. They rely on eyeballing a handful of conversations. Build an open-source
harness that turns agent quality into numbers a CI pipeline can gate on: scenarios defined in YAML,
run against the agent, scored on several dimensions, failing the build when a score regresses.

## Functional requirements

1. Scenario format: YAML defining a user persona, opening message, a scripted or simulated
   multi-turn user, available tools, and the expected outcome.
2. Simulated user: an LLM plays the user so conversations run multi-turn without a human, and can be
   difficult (vague, changes their mind, gives wrong IDs).
3. Metrics, at minimum four:
   - Task completion (did the agent reach the expected outcome)
   - Tool-call accuracy (right tool, right arguments, no hallucinated tools)
   - Groundedness (claims supported by tool output or retrieved context, LLM-judged)
   - Efficiency (turns, tokens, cost per resolved task)
4. LLM-as-judge with a rubric, AND a validation of the judge: hand-label 50 conversations and report
   judge agreement with those labels. An unvalidated judge is worthless.
5. Regression gates: a baseline score file; the run fails if any metric drops past a threshold.
6. Tracing: OpenTelemetry spans per turn / model call / tool call with tokens and latency.
7. Reports: HTML or markdown per run with per-scenario pass/fail, failing transcripts, baseline diff.
8. CLI: `agent-eval run --suite suites/support.yaml --baseline baselines/v1.json`

## Non-functional requirements

- Concurrent scenario execution with a concurrency limit and a total token budget that aborts the run.
- Model-agnostic: any OpenAI-compatible endpoint, plus a local model via Ollama so a reader without
  API credits can run it.
- Deterministic replay: cache model responses so runs repeat without spending tokens.

## Stack

Python 3.11, Pydantic, asyncio, LiteLLM or httpx, OpenTelemetry SDK, Jinja2, pytest, Ruff, GH Actions.

## Acceptance criteria

- [ ] 20+ scenarios across 3+ intents, including 2 adversarial
- [ ] 4 metrics implemented, judge agreement reported on 50 hand-labelled conversations
- [ ] CI workflow running a small suite per PR, failing on regression
- [ ] Traces viewable locally, screenshot in README
- [ ] DESIGN.md covering judge reliability, cost control, what breaks at 10,000 scenarios

## Resume line it earns

Built and open-sourced an agent evaluation harness (scenario simulation, LLM-as-judge with validated
rubric, tool-call accuracy, OpenTelemetry tracing) that gates agent releases in CI; judge agreement
with human labels of X% across N scenarios.
