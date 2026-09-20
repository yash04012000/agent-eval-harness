# PRD 1 — Foundations: scenario schema, model-provider abstraction, cache/replay

Status: Done · Depends on: nothing · Blocks: PRDs 2-6

## Summary

Before anything runs a conversation, three interfaces need to exist and be stable, because every
later PRD builds against them: how a scenario is described in YAML, how the harness talks to a
model regardless of provider, and how a model response gets cached so a run is replayable without
spending tokens or holding API credentials. Get these three right once; everything else is built
on top, not around.

## Goals

- Define the scenario YAML schema and its Pydantic model, covering persona, opening message,
  scripted-or-simulated user config, tool definitions, and expected outcome.
- Define a `ModelClient` interface that the rest of the system calls, backed by one implementation
  that reaches any OpenAI-compatible endpoint and a local Ollama model.
- Define a deterministic cache/replay layer keyed on request content, with a `record` mode (hits
  the real API, writes the cache) and a `replay` mode (cache-only, hard-fails on a miss — this is
  what CI runs).
- Ship a `scripts/validate_scenarios.py` (or pytest suite) that loads every YAML file in
  `suites/` and confirms it parses against the schema, so a malformed scenario fails fast and
  loud instead of surfacing as a confusing runtime error three layers in.

## Non-goals

- Actually running a conversation (PRD 2).
- Scoring anything (PRD 3, 4).
- The CLI entry point (PRD 5) — this PRD ships library code and tests, not `agent-eval run`.

## Design

### 1. Scenario schema

```python
# harness/scenario.py
from enum import Enum
from pydantic import BaseModel, Field

class Difficulty(str, Enum):
    NORMAL = "normal"
    VAGUE = "vague"
    CHANGES_MIND = "changes_mind"
    WRONG_IDS = "wrong_ids"
    ADVERSARIAL = "adversarial"

class Persona(BaseModel):
    name: str
    goal: str                      # what the simulated user is trying to accomplish
    traits: list[str] = []         # e.g. ["impatient", "non-technical"]
    difficulty: Difficulty = Difficulty.NORMAL

class ScriptedTurn(BaseModel):
    user: str

class UserSimulation(BaseModel):
    mode: Literal["scripted", "simulated"]
    persona: Persona | None = None          # required if mode == "simulated"
    script: list[ScriptedTurn] | None = None  # required if mode == "scripted"
    max_turns: int = 12
    simulator_model: str | None = None      # override; default from run config

class ToolDef(BaseModel):
    name: str
    description: str
    parameters: dict                        # JSON Schema, passed straight to the agent
    # mock behavior: a lookup table keyed by a canonical repr of the call args,
    # falling back to `default_response`. Kept data-only (no eval'd code) so scenario
    # YAML can't execute arbitrary logic.
    responses: dict[str, dict] = {}
    default_response: dict | None = None

class ExpectedOutcome(BaseModel):
    resolution: Literal["resolved", "escalated", "refused"]
    required_tool_calls: list[str] = []     # tool names that must appear, any order
    forbidden_tool_calls: list[str] = []    # tool names that must never appear
    must_mention: list[str] = []            # substrings the final agent message should contain
    must_not_mention: list[str] = []

class Scenario(BaseModel):
    id: str
    intent: str                             # e.g. "billing", "returns", "account_access"
    description: str
    adversarial: bool = False
    opening_message: str
    user_simulation: UserSimulation
    tools: list[ToolDef] = []
    expected_outcome: ExpectedOutcome
    token_budget: int | None = None         # overrides run-level default
```

Decisions worth flagging:

- **Tool mocks are data, not code.** A `responses` lookup table plus a `default_response`,
  matched on a canonical JSON repr of the call arguments. This keeps scenario YAML safe to load
  from anywhere (no arbitrary Python in scenario files) and keeps tool behavior visible in the
  diff when a scenario changes. If a scenario genuinely needs stateful tool behavior (e.g. a
  second call should see the first call's effect), that's solved with a small per-scenario Python
  hook registered by id in `harness/tool_hooks.py` — the exception path, not the default.
- **`required_tool_calls` / `forbidden_tool_calls` live in the schema, not bolted onto the judge**
  — tool-call accuracy (PRD 3) is deterministic and shouldn't depend on an LLM judge to check
  whether a hallucinated tool got called.

### 2. Model-provider abstraction

Problem statement allows LiteLLM or httpx. Decision: **LiteLLM**, wrapped behind a narrow
interface so the choice is swappable later without touching call sites.

Reasoning to record in DESIGN.md's "options considered and rejected": raw httpx means hand-rolling
request/response shape normalization across OpenAI-compatible providers and Ollama; LiteLLM already
does that and supports Ollama's local endpoint out of the box, which directly serves the
non-functional requirement that a reader without API credits can run the suite. The cost is an
extra dependency and one more layer to understand when something breaks — acceptable for a 3-4
week solo build; would reconsider if the harness ever needed to shed dependencies for a
minimal-footprint embed.

```python
# harness/model_client.py
class ModelResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = []
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    raw: dict                          # untouched provider response, for tracing

class ModelClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        **kwargs,
    ) -> ModelResponse: ...
```

`LiteLLMModelClient` implements this by calling `litellm.acompletion(...)`. Every call — agent,
simulated user, and judge — goes through this one interface, which is also the single seam PRD 5's
OTel instrumentation wraps (one decorator, every model call traced, instead of three call sites to
remember).

### 3. Cache / replay

Non-functional requirement: "cache model responses so runs repeat without spending tokens." This
also has to serve CI (no secrets available) and the judge-validation study in PRD 4 (the 50
hand-labeled conversations must be scoreable identically by anyone who clones the repo).

```python
# harness/cache.py
class CacheMode(str, Enum):
    RECORD = "record"   # call the real API, write the cache entry
    REPLAY = "replay"    # cache only; a miss is a hard error
    LIVE = "live"         # bypass the cache entirely (local dev iteration)

def cache_key(model: str, messages: list[dict], tools: list[dict] | None, temperature: float) -> str:
    # stable hash over a canonicalized (sorted-keys, no timestamps) JSON repr
    ...
```

Storage: flat files under `cache/<sha256>.json` (request digest → `ModelResponse`), committed to
git for every scenario in `suites/` so CI runs in `replay` mode with zero API keys. A `Makefile`
target (`make record-cache SUITE=suites/support.yaml`) regenerates it deliberately when scenarios
or prompts change — this is the one-command-reproducibility story for the model-response side.

Cache entries are content-addressed and provider-agnostic in shape, so switching the demo between
an OpenAI-compatible endpoint and Ollama doesn't invalidate the committed cache as long as the
recorded model name is what's replayed.

### File/module layout this PRD produces

```
harness/
  scenario.py        # Scenario, Persona, ToolDef, etc. (Pydantic models)
  model_client.py     # ModelClient protocol + LiteLLMModelClient
  cache.py             # cache_key, CachedModelClient wrapper, CacheMode
  tool_hooks.py        # registry for the stateful-tool escape hatch
tests/
  test_scenario_schema.py
  test_model_client.py   # against a fake transport, no network
  test_cache.py            # record → replay round-trip, hash stability
scripts/
  validate_scenarios.py
suites/
  _schema_smoke.yaml    # one minimal scenario used only to exercise the loader in tests
```

## Testing plan

- Schema: valid scenario parses; missing `persona` when `mode: simulated` raises; malformed tool
  JSON Schema raises.
- Model client: a fake transport returns a canned response; confirm token counts and latency are
  captured, confirm the interface doesn't leak provider-specific response shapes.
- Cache: same request twice in `replay` mode returns the identical cached response with zero
  network calls (assert via a transport call counter); a cache miss in `replay` mode raises;
  `record` mode writes a file whose key matches `cache_key(...)`.

## Acceptance criteria this PRD unblocks

Not directly checkable itself, but a prerequisite for: "20+ scenarios" (needs the schema),
"model-agnostic... plus Ollama" (needs the provider abstraction), "deterministic replay" (needs
the cache).

## Open questions for review

1. Is `responses` keyed by canonical-arg-repr sufficient, or do any planned scenarios need
   call-order-dependent tool state badly enough to justify building the hook mechanism now instead
   of deferring it?
2. LiteLLM pin version — pin to a specific release now so the committed cache format doesn't shift
   under a minor version bump mid-project.
3. Should `token_budget` be enforced per-scenario (this PRD's schema) or only at the run level
   (PRD 2)? Leaning: schema carries an optional override, PRD 2 owns enforcement and the
   run-level aggregate abort.
