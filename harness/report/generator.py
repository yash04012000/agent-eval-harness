"""Renders a `SuiteReport` + `GateResult` into HTML and Markdown reports (PRD 5).

Markdown is what a PR comment or terminal-based reviewer wants; HTML is what a browser-based
reviewer (and the README trace/report screenshot) wants. Both render from the same data so they
can never disagree with each other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict

from harness.gate import GateResult
from harness.metrics.aggregate import SuiteReport
from harness.metrics.base import MetricResult
from harness.transcript import Transcript

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_METRICS = (
    "task_completion_rate",
    "tool_call_accuracy_mean",
    "groundedness_mean",
    "cost_per_resolved_task",
)


class ScenarioReportRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    intent: str
    task_completion: MetricResult
    tool_call_accuracy: MetricResult
    efficiency: MetricResult
    transcript: Transcript
    groundedness: MetricResult | None = None

    @property
    def passed(self) -> bool:
        return bool(self.task_completion.passed)


def _summary_rows(
    report: SuiteReport, baseline: dict[str, Any] | None, gate: GateResult
) -> list[dict[str, Any]]:
    current = {
        "task_completion_rate": report.task_completion_rate,
        "tool_call_accuracy_mean": report.tool_call_accuracy_mean,
        "groundedness_mean": report.groundedness_mean,
        "cost_per_resolved_task": report.cost_per_resolved_task,
    }
    baseline_metrics = (baseline or {}).get("metrics", {})
    violated = {v.metric for v in gate.violations}

    rows = []
    for metric in _METRICS:
        current_value = current[metric]
        baseline_value = baseline_metrics.get(metric)
        if current_value is None:
            status = "n/a"
        elif metric in violated:
            status = "FAIL"
        elif metric not in baseline_metrics:
            status = "no baseline"
        else:
            status = "ok"
        rows.append(
            {
                "metric": metric,
                "baseline": baseline_value,
                "current": current_value,
                "status": status,
            }
        )
    return rows


def generate(
    report: SuiteReport,
    gate: GateResult,
    baseline: dict[str, Any] | None,
    rows: list[ScenarioReportRow],
    out_dir: Path | str,
    suite_name: str = "",
    model: str = "",
) -> None:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    context = {
        "report": report,
        "gate": gate,
        "summary_rows": _summary_rows(report, baseline, gate),
        "rows": rows,
        "suite_name": suite_name,
        "model": model,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    (out_path / "report.md").write_text(
        env.get_template("report.md.j2").render(**context), encoding="utf-8"
    )
    (out_path / "report.html").write_text(
        env.get_template("report.html.j2").render(**context), encoding="utf-8"
    )
