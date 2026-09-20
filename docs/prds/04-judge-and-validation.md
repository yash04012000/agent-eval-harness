# PRD 4 — LLM-as-judge (groundedness) and judge validation

Status: Draft · Depends on: PRD 1, 2, 3 · Blocks: PRD 5 (gate needs `groundedness_mean` filled in)

## Summary

Groundedness is the one required metric that can't be checked deterministically — it needs
judgment about whether a claim in the agent's message is actually supported by what the tools
returned. The problem statement is explicit that an unvalidated judge is worthless, so this PRD is
really two things: the judge itself, and a validation study (50 hand-labeled conversations, judge
agreement reported) that either earns trust in it or documents exactly where it can't be trusted.
This is also the PRD that produces the "judge agreement with human labels of X% across N
scenarios" line the resume entry names directly — it's the highest-scrutiny deliverable in the
project.

## Goals

- `GroundednessMetric`: judge model reads a transcript, decides per-claim and overall whether the
  agent's statements are supported by tool output, using the same cached `ModelClient` as
  everything else (so judge calls replay deterministically in CI, same as agent/user calls).
- A categorical rubric (`grounded` / `partial` / `not_grounded`) rather than a raw numeric score,
  because categories are what a human labeler can apply consistently and what an agreement
  statistic (Cohen's kappa) is designed to compare.
- A labeling workflow that gets a human (the repo owner) to label 50 conversations against the
  same categories, independent of having seen the judge's verdict first.
- An agreement report: raw agreement %, Cohen's kappa, and a confusion matrix, written to a
  committed artifact — this is evidence, not just a log line, so it needs to survive in the repo.

## Non-goals

- Building a general claim-extraction NLP pipeline. The judge does claim identification and
  verification in one structured LLM call; there's no separate claim-extraction model.
- A UI for labeling. A terminal-driven script producing a CSV is enough for 50 rows done once by
  one person.

## Design

### Rubric and judge output

```python
# harness/judge/schema.py
class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    evidence: str | None       # quoted tool output or context that supports/contradicts it

class JudgeVerdict(BaseModel):
    verdict: Literal["grounded", "partial", "not_grounded"]
    rationale: str
    claims: list[ClaimVerdict] = []
```

`grounded`: every factual claim in the agent's final message is traceable to a tool result or the
conversation itself. `not_grounded`: at least one claim contradicts or has no basis in available
evidence (a hallucination). `partial`: a mix, or a claim that's plausible but unverifiable given
what the tools returned (e.g. the agent asserts something no tool call ever checked).

```python
# harness/judge/rubric.py — Jinja2 template, rendered with scenario + transcript + tool outputs
JUDGE_PROMPT = """
You are auditing an assistant's final response for factual grounding.
Tool calls and their results from this conversation:
{{ tool_calls_and_results }}

Assistant's message under audit:
{{ final_message }}

Identify each factual claim the assistant made. For each, decide if it is supported by the tool
results above or the user's own statements. Respond with the JSON schema you were given.
"""
```

```python
# harness/metrics/groundedness.py
_VERDICT_SCORE = {"grounded": 1.0, "partial": 0.5, "not_grounded": 0.0}

async def score(transcript, scenario, judge_client: ModelClient, judge_model: str) -> MetricResult:
    verdict = await run_judge(transcript, scenario, judge_client, judge_model)   # parses JudgeVerdict, retries once on invalid JSON
    return MetricResult(name="groundedness", score=_VERDICT_SCORE[verdict.verdict],
                         passed=verdict.verdict != "not_grounded",
                         details={"verdict": verdict.verdict, "rationale": verdict.rationale,
                                   "claims": [c.model_dump() for c in verdict.claims]})
```

Judge calls go through the same `CachedModelClient` from PRD 1 — same cache key scheme, same
replay-mode guarantee — so a CI run never calls a live judge, and the validation study is exactly
reproducible from the committed cache.

### Where 50 conversations come from

The suite only requires 20+ scenarios; the validation set needs 50 conversations. Rather than
inflate the demo suite past what's needed for good scenario coverage, the labeling set is built by
running the full suite through the reference agent with **2-3 simulated-user seeds per scenario**
(different random seed → different vague/wrong-ID/changes-mind specifics from the same persona),
producing 50+ distinct transcripts from ~20-25 scenarios. This is recorded once (`record` mode,
real API calls, committed to cache) and then everything downstream — judge, human labeling,
agreement report — runs against that fixed, cached set of transcripts forever.

### Human labeling

```python
# scripts/label_conversations.py
# For each transcript in the validation set (in random order, judge verdict hidden):
#   print the conversation + tool calls
#   prompt: "grounded / partial / not_grounded ?"
#   append {transcript_id, human_verdict, notes, labeled_at} to data/human_labels.csv
```

Labeling happens *blind* to the judge's verdict (script doesn't show it) to avoid anchoring the
human label on the thing being validated. `data/human_labels.csv` is committed — it's the repo
owner's own labels on synthetic scenarios, not real user data, so it's fine to check in per the
portfolio's no-real-data rule.

### Agreement report

```python
# scripts/judge_validation_report.py
def cohens_kappa(human: list[str], judge: list[str], categories: list[str]) -> float: ...

def build_report(human_labels_csv, cached_transcripts) -> str:
    judge_verdicts = [replay_judge(t) for t in cached_transcripts]   # replay mode, no live calls
    human_verdicts = [row.human_verdict for row in read_csv(human_labels_csv)]
    raw_agreement = mean(h == j for h, j in zip(human_verdicts, judge_verdicts))
    kappa = cohens_kappa(human_verdicts, judge_verdicts, ["grounded", "partial", "not_grounded"])
    confusion = confusion_matrix(human_verdicts, judge_verdicts)
    # renders results/judge_validation_report.md: raw agreement, kappa, confusion matrix,
    # and every disagreement listed with both verdicts + rationale, so a reader can audit
    # *which kinds* of claims the judge gets wrong, not just a summary number.
```

Kappa (not raw agreement alone) is the headline number because raw agreement is inflated by
however skewed the label distribution is (if 40 of 50 conversations are trivially `grounded`,
a judge that always says `grounded` looks 80% "accurate" while being useless). Landis & Koch's
convention (κ ≥ 0.6 "substantial") is used as the documented bar for "this judge is trustworthy
enough to gate on" in DESIGN.md — if the harness doesn't clear it, that's reported honestly as a
limitation, not hidden.

### File/module layout

```
harness/judge/
  schema.py
  rubric.py
harness/metrics/
  groundedness.py
scripts/
  label_conversations.py
  judge_validation_report.py
data/
  human_labels.csv                 # committed
results/
  judge_validation_report.md       # committed, generated
tests/
  test_groundedness_metric.py      # fake judge ModelClient, verdict parsing + retry-on-bad-json
  test_agreement_stats.py           # cohens_kappa against a hand-computed known confusion matrix
```

## Testing plan

`cohens_kappa` and the confusion-matrix logic are pure math, tested against a hand-computed
fixture (a known 3x3 confusion matrix with a kappa value computed independently, e.g. by hand or
cross-checked against `sklearn.metrics.cohen_kappa_score` in a test, without adding sklearn as a
runtime dependency — just to sanity-check the implementation once). The judge metric itself is
tested against a fake `ModelClient` returning a fixed `JudgeVerdict` JSON string, including a
malformed-JSON case to verify the retry path. The actual 50-conversation agreement number is not a
unit test result — it's a one-time (re-run whenever the rubric changes) generated report, committed
as evidence.

## Acceptance criteria this PRD unblocks

"4 metrics implemented" (completing groundedness) and "judge agreement reported on 50
hand-labelled conversations" — directly and entirely.

## Open questions for review

1. Judge model choice: same model family as the agent-under-test, or deliberately a stronger/
   different model to avoid the judge sharing the agent's blind spots? Recommendation: a different,
   stronger model as judge (e.g. agent on a smaller/local model, judge on a frontier model) —
   record the reasoning either way in DESIGN.md since it's a real trade-off (cost vs. bias).
2. If κ comes back below 0.6 on the first labeling pass, is the fallback (a) revise the rubric and
   re-label, or (b) ship it with the low score reported honestly as a limitation? For a portfolio
   piece, an honestly-reported 0.45 with analysis of *why* may read better than a suspiciously
   perfect 0.9 — worth deciding the posture before the number exists, not after.
3. Confirm 2-3 seeds per scenario is an acceptable way to reach 50 conversations rather than
   writing 50 distinct scenarios — trades scenario-authoring effort for slightly less diversity in
   the validation set.
