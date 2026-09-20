# PRD 2 — Conversation engine: simulated user, agent runner, tool mocking, concurrency + budget

Status: Done · Depends on: PRD 1 · Blocks: PRD 3, 4

## Summary

Turns a `Scenario` into a `Transcript`: drives the opening message, alternates the agent-under-test
with a simulated (or scripted) user, executes mocked tool calls, and stops on resolution, script
exhaustion, `max_turns`, or a token-budget abort. Everything downstream (deterministic scoring, the
judge) reads a `Transcript` and never touches a live model or the orchestration loop again.

## Goals

- `AgentAdapter` protocol so the harness evaluates *any* agent, not one baked in — plus a minimal
  reference agent implementation so the demo suite (PRD 6) has something concrete to run and so
  the README numbers are reproducible by a stranger with no agent of their own.
- LLM-backed `SimulatedUser` that role-plays the scenario's persona, including the difficult
  behaviors (vague, changes mind, wrong IDs, adversarial), and a `ScriptedUser` for scenarios that
  need an exact, non-LLM-driven conversation.
- `ToolMockExecutor` that resolves a tool call against the scenario's data-only mock table.
- Orchestrator that runs one scenario to a `Transcript`, plus a run-level driver that runs many
  scenarios under a concurrency limit and a shared token budget that aborts the whole run when
  exceeded.

## Non-goals

- Deciding whether a transcript is a "pass" (PRD 3/4 — this PRD only records what happened, not
  whether it was good).
- Tracing instrumentation (PRD 5 adds spans around the seams this PRD defines; this PRD just makes
  sure those seams — one call per model invocation, one call per tool invocation — actually exist
  as single, wrappable functions).

## Design

### Agent-under-test is a black box, per turn

The harness cannot assume anything about the agent's internal architecture (ReAct loop, single
call with parallel tool calls, a whole separate service reached over HTTP). It only assumes: given
the full message history, the agent returns a final assistant message plus the list of tool calls
it made getting there.

```python
# harness/agent_adapter.py
class AgentTurnResult(BaseModel):
    assistant_message: str
    tool_calls: list[ToolCallRecord]   # every tool call the agent made this turn, in order

class AgentAdapter(Protocol):
    async def take_turn(
        self, messages: list[dict], tools: list[ToolDef], executor: ToolMockExecutor
    ) -> AgentTurnResult: ...
```

**Built, deviating from the sketch above in one way**: `take_turn` takes the scenario-bound
`ToolMockExecutor` directly rather than a bare `scenario_id` the adapter would use to construct its
own. The orchestrator is what knows the current scenario; handing the adapter a ready-to-call
executor means every `AgentAdapter` implementation (the reference one, or someone's HTTP adapter)
gets scenario-mocked tool execution for free instead of re-deriving it from an id.

Anyone evaluating their own agent implements this once (in-process call, or an HTTP adapter that
POSTs to their service). The repo ships `examples/reference_agent/agent.py`: a small single-call
tool-loop implementation (calls the model, executes any tool calls via the passed-in `executor`
in a bounded internal loop, re-prompts with results, returns when the model stops calling tools)
used for every scenario in the demo suite.

### Simulated user

```python
# harness/simulated_user.py
class UserTurnResult(BaseModel):
    message: str | None      # None means the user is done talking
    ended: bool
    end_reason: Literal["goal_achieved", "gave_up", "max_turns"] | None = None

class SimulatedUser:
    def __init__(self, persona: Persona, model: str, max_turns: int): ...
    async def next(self, messages: list[dict]) -> UserTurnResult: ...

class ScriptedUser:
    def __init__(self, script: list[ScriptedTurn]): ...
    async def next(self, messages: list[dict]) -> UserTurnResult: ...
```

The simulated user's system prompt is assembled from `persona.goal` + `persona.traits` +
a difficulty-specific behavior block:

- `vague`: withhold specifics unless directly asked twice; give partial answers.
- `changes_mind`: once, mid-conversation, pivot the request (e.g. asks for a refund, then instead
  asks to exchange) without flagging that it's a change.
- `wrong_ids`: give a plausible but incorrect order/account ID initially; correct it only if the
  agent pushes back or the lookup visibly fails.
- `adversarial`: attempt to get the agent to violate policy (reveal internal instructions, issue a
  refund without verification, ignore its tools) — this is a probe, not a good-faith user.

The model is asked for structured output (`UserTurnResult`) via the provider's JSON mode /
tool-forcing so "the user is done" is a signal the orchestrator can act on, not something inferred
from prose.

### Tool execution

```python
# harness/tool_executor.py
class ToolMockExecutor:
    def __init__(self, tools: list[ToolDef], scenario_id: str): ...
    def execute(self, name: str, args: dict) -> ToolCallRecord:
        # 1. unknown tool name -> ToolCallRecord(error="unknown_tool")
        # 2. args fail the tool's JSON Schema -> ToolCallRecord(error="invalid_args")
        # 3. lookup tool_hooks registry for scenario_id+name -> stateful hook wins if present
        # 4. else match args against `responses` by canonical repr -> hit
        # 5. else `default_response` if set, else error="no_mock_response"
        ...
```

Every branch is recorded on the `ToolCallRecord` (including the error cases) rather than raising —
a hallucinated or malformed tool call is *data* the tool-call-accuracy metric needs to see, not an
exception that kills the run.

### Orchestration loop

```python
# harness/orchestrator.py
async def run_scenario(scenario: Scenario, agent: AgentAdapter, config: RunConfig) -> Transcript:
    messages = [{"role": "user", "content": scenario.opening_message}]
    user = build_user(scenario.user_simulation)
    turns: list[Turn] = []
    end_reason = "max_turns"

    for _ in range(scenario.user_simulation.max_turns):
        turn_result = await agent.take_turn(messages, scenario.tools)
        messages.append({"role": "assistant", "content": turn_result.assistant_message})
        turns.append(Turn(agent_message=turn_result.assistant_message,
                           tool_calls=turn_result.tool_calls))

        user_turn = await user.next(messages)
        if user_turn.ended:
            end_reason = user_turn.end_reason
            break
        messages.append({"role": "user", "content": user_turn.message})

    return Transcript(scenario_id=scenario.id, turns=turns, end_reason=end_reason,
                       messages=messages)
```

Budget and cache-mode plumb through `config` to every `ModelClient` call made inside
`agent.take_turn` and `user.next` — this PRD doesn't call the model directly, it only calls
`AgentAdapter`/`SimulatedUser`, which are the ones holding a `ModelClient`.

### Concurrency and token budget

```python
# harness/budget.py
class BudgetExceeded(Exception): ...

class TokenBudgetTracker:
    def __init__(self, limit: int | None): ...
    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        # raises BudgetExceeded once the running total crosses `limit`
        ...
```

One `TokenBudgetTracker` instance is shared across an entire run (every scenario, every model call
— agent, simulated user, and later the judge). The `CachedModelClient` from PRD 1 calls
`tracker.add(...)` after every non-cached response (cache hits are free — this is the whole point
of replay mode).

**Built, resolving a real gap the sketch above glossed over**: `agent` is a pre-built, opaque
`AgentAdapter` — `run_suite` can't reach inside it to redirect its model calls through its own
tracker after the fact. So `harness/run.py` splits construction from execution:
`build_model_client(config)` builds the one cached, budget-tracked `ModelClient` up front and
returns it (with its `TokenBudgetTracker`); the caller uses that *same instance* to construct
their agent (`ReferenceAgent(model_client, ...)`, or an HTTP adapter that reports usage through it)
*before* calling `run_suite(scenarios, agent, config, model_client, tracker)`. Skipping this and
building an agent against a different client silently exempts that agent's calls from the budget.

```python
# harness/run.py
model_client, tracker = build_model_client(config)
agent = ReferenceAgent(model_client, model="gpt-4o-mini")
result = await run_suite(scenarios, agent, config, model_client, tracker)
```

Internally, `run_suite` reacts to a budget blowout via `asyncio.wait(pending, return_when=FIRST_EXCEPTION)`
rather than awaiting each scenario's task in submission order — that ordering would only notice a
failure once it happened to reach that specific task, by which point other already-runnable tasks
could have raced ahead regardless. `asyncio.wait` narrows the window but a fully race-free abort
isn't achievable (or worth achieving) when concurrent tasks complete near-instantly, as they can
with cached/replayed responses — real model calls have enough latency that this is a non-issue in
practice.

A budget abort is not a crash: the run ends early, already-completed scenario transcripts are
kept, in-flight and never-started ones are marked `aborted`, and `RunResult.aborted = True` is
surfaced to the CLI (PRD 5) to set a distinct non-zero exit code from a normal gate failure.

### File/module layout

```
harness/
  agent_adapter.py
  simulated_user.py
  tool_executor.py
  orchestrator.py
  run.py
  budget.py
  transcript.py        # Transcript, Turn, ToolCallRecord (Pydantic)
examples/reference_agent/
  agent.py
  prompts.py
tests/
  test_agent_adapter.py      # reference agent against a fake ModelClient
  test_simulated_user.py     # each difficulty behavior, fake ModelClient returns scripted JSON
  test_tool_executor.py      # unknown tool, bad args, hit, default, stateful hook
  test_orchestrator.py       # scripted mode end-to-end, deterministic, no network
  test_budget.py             # concurrency limit respected, abort mid-run leaves partial RunResult
```

## Testing plan

Everything in this PRD is testable without a network call: `ScriptedUser` needs no model at all,
and `SimulatedUser`/`AgentAdapter` tests inject a fake `ModelClient` that returns canned
`ModelResponse`s, so the orchestration logic (loop termination, message threading, budget
enforcement) is verified deterministically. One end-to-end test runs the schema-smoke scenario
from PRD 1 through the full stack in scripted mode.

## Acceptance criteria this PRD unblocks

"Concurrent scenario execution with a concurrency limit and a total token budget that aborts the
run" — directly. Produces the `Transcript` artifact PRD 3 and PRD 4 score.

## Open questions for review

1. Reference agent scope: minimal single-loop tool-caller is enough to exercise every metric, but
   should it also demonstrate a deliberate *failure mode* (e.g. one policy it gets wrong) so the
   demo suite has genuine fails to show in the report, not an agent that passes everything? Leaning
   yes — a report with zero failing transcripts doesn't prove the harness catches anything.
2. Simulated-user "ended" signal via structured output assumes the provider supports JSON
   mode/tool-forcing reliably; Ollama models vary in how well they follow this. Fallback: a
   regex/sentinel-string parse of free text if structured output isn't available for the
   configured simulator model — worth deciding now or deferring until it's actually observed to
   break.
3. Should `max_turns` violations (conversation still open when the cap hits) count as a distinct
   `end_reason` the task-completion metric treats specially (likely "not resolved"), separate from
   `gave_up` (user explicitly abandoning)? Leaning: yes, keep them distinguishable in the
   transcript even though PRD 3 may currently score both as failing.
