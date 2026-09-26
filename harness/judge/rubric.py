"""Renders the groundedness rubric and drives the judge model call (PRD 4).

The judge is forced to answer through a tool call (`submit_groundedness_verdict`) rather than
free-text JSON -- the same pattern PRD 2's `SimulatedUser` uses for `respond_as_user` -- because
small/local judge models (this project's default, see DESIGN.md) are far more reliable at filling
a tool-call schema than at emitting bare JSON on request. A free-text fallback still exists for any
`ModelClient` that ignores `tool_choice`.
"""

from __future__ import annotations

import json

from jinja2 import Template
from pydantic import ValidationError

from harness.judge.schema import JudgeVerdict
from harness.model_client import ModelClient
from harness.scenario import Scenario
from harness.transcript import Transcript, all_tool_calls, final_message

JUDGE_PROMPT = Template(
    """You are auditing an assistant's final response for factual grounding.

Tool calls and their results from this conversation:
{{ tool_calls_and_results }}

Assistant's message under audit:
{{ final_message }}

Identify each factual claim the assistant made. For each, decide if it is supported by the tool
results above or the user's own statements. Respond by calling `submit_groundedness_verdict`.
"""
)

_VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_groundedness_verdict",
        "description": "Submit the groundedness audit verdict for the assistant's final message.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["grounded", "partial", "not_grounded"],
                },
                "rationale": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string"},
                            "supported": {"type": "boolean"},
                            "evidence": {"type": ["string", "null"]},
                        },
                        "required": ["claim", "supported"],
                    },
                },
            },
            "required": ["verdict", "rationale"],
        },
    },
}


class JudgeParseError(Exception):
    """Raised when the judge's response couldn't be parsed into a `JudgeVerdict` after a retry."""


def _format_tool_calls(transcript: Transcript) -> str:
    calls = all_tool_calls(transcript)
    if not calls:
        return "(no tool calls were made)"
    lines = []
    for call in calls:
        result = call.response if call.response is not None else {"error": call.error}
        lines.append(f"- {call.name}({json.dumps(call.arguments)}) -> {json.dumps(result)}")
    return "\n".join(lines)


def render_judge_prompt(transcript: Transcript, scenario: Scenario) -> str:
    return JUDGE_PROMPT.render(
        tool_calls_and_results=_format_tool_calls(transcript),
        final_message=final_message(transcript),
    )


def _normalize_verdict_args(args: dict) -> dict:
    """Small local models sometimes stringify the nested `claims` array inside tool-call
    arguments (e.g. `"claims": "[{...}, {...}]"` instead of an actual JSON array), and that
    string is itself occasionally malformed (inconsistent quote-escaping once an "evidence" value
    contains quoted tool output). `claims` is supplementary detail, not what groundedness is
    scored on -- so a claims field that can't be recovered is dropped (empty list) rather than
    failing the whole verdict over formatting noise in one nested field.
    """
    claims = args.get("claims")
    if isinstance(claims, str):
        try:
            args = {**args, "claims": json.loads(claims)}
        except json.JSONDecodeError:
            args = {**args, "claims": []}
    return args


def _parse_verdict(response) -> JudgeVerdict | None:
    if response.tool_calls:
        args = _normalize_verdict_args(response.tool_calls[0].arguments)
        try:
            return JudgeVerdict.model_validate(args)
        except ValidationError:
            return None
    if response.content:
        try:
            return JudgeVerdict.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, ValidationError):
            return None
    return None


async def run_judge(
    transcript: Transcript,
    scenario: Scenario,
    judge_client: ModelClient,
    judge_model: str,
) -> JudgeVerdict:
    prompt = render_judge_prompt(transcript, scenario)
    messages = [{"role": "user", "content": prompt}]

    for _attempt in range(2):
        response = await judge_client.complete(
            model=judge_model,
            messages=messages,
            tools=[_VERDICT_TOOL],
            temperature=0.0,
            tool_choice={"type": "function", "function": {"name": "submit_groundedness_verdict"}},
        )
        verdict = _parse_verdict(response)
        if verdict is not None:
            return verdict

    raise JudgeParseError(
        f"judge model {judge_model!r} did not return a parseable verdict for "
        f"scenario {scenario.id!r} after a retry"
    )
