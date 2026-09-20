# PRD index — agent-eval-harness

Six PRDs, built in order. Each is buildable and testable before the next starts. Update the
status column as work lands.

| # | PRD | Covers | Status |
|---|-----|--------|--------|
| 1 | [01-foundations.md](01-foundations.md) | Scenario schema, model-provider abstraction, deterministic cache/replay | Draft |
| 2 | [02-conversation-engine.md](02-conversation-engine.md) | Simulated user, agent runner, tool mocking, concurrency + token budget | Draft |
| 3 | [03-deterministic-scoring.md](03-deterministic-scoring.md) | Task completion, tool-call accuracy, efficiency metrics | Draft |
| 4 | [04-judge-and-validation.md](04-judge-and-validation.md) | Groundedness rubric, LLM-as-judge, 50-label agreement study | Draft |
| 5 | [05-gates-tracing-reporting-cli.md](05-gates-tracing-reporting-cli.md) | Baseline/regression gate, OpenTelemetry spans, report generator, `agent-eval` CLI | Draft |
| 6 | [06-content-and-ci.md](06-content-and-ci.md) | Scenario suite (20+, 4 intents, 2 adversarial), GH Actions gate, DESIGN.md/README numbers | Draft |

## Why this order

PRD 1 is load-bearing for everything else: the scenario schema is what every later PRD reads,
the provider abstraction is what every model call goes through, and the cache/replay format is
what makes CI runnable without secrets (non-functional requirement) and what PRD 4's judge
validation needs to be reproducible. Get those three interfaces wrong and PRDs 2-6 inherit the
mistake. PRDs 2-4 each produce one artifact the next stage consumes (transcripts → scores →
validated judge). PRD 5 is integration: nothing it needs doesn't already exist. PRD 6 is content
and proof — it's what turns the acceptance criteria into checked boxes.
