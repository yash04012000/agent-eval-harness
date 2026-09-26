from harness.gate import GateResult, Violation
from harness.metrics.aggregate import ScenarioResult, SuiteReport
from harness.metrics.base import MetricResult
from harness.report.generator import ScenarioReportRow, generate
from harness.transcript import ToolCallRecord, Transcript, Turn


def _passing_row() -> ScenarioReportRow:
    transcript = Transcript(
        scenario_id="billing_1",
        end_reason="goal_achieved",
        turns=[
            Turn(
                agent_message="Your refund of $20 has been issued.",
                tool_calls=[
                    ToolCallRecord(
                        id="c1",
                        name="issue_refund",
                        arguments={"order_id": "A1", "amount": 20},
                        response={"status": "ok"},
                    )
                ],
            )
        ],
    )
    return ScenarioReportRow(
        scenario_id="billing_1",
        intent="billing",
        task_completion=MetricResult(name="task_completion", score=1.0, passed=True, details={}),
        tool_call_accuracy=MetricResult(
            name="tool_call_accuracy", score=1.0, passed=True, details={}
        ),
        efficiency=MetricResult(name="efficiency", score=1.0, passed=None, details={}),
        groundedness=MetricResult(
            name="groundedness",
            score=1.0,
            passed=True,
            details={"verdict": "grounded", "rationale": "matches tool output"},
        ),
        transcript=transcript,
    )


def _failing_row() -> ScenarioReportRow:
    transcript = Transcript(
        scenario_id="order_status_1",
        end_reason="gave_up",
        turns=[Turn(agent_message="Your order was refunded in full.", tool_calls=[])],
    )
    return ScenarioReportRow(
        scenario_id="order_status_1",
        intent="order_status",
        task_completion=MetricResult(
            name="task_completion",
            score=0.0,
            passed=False,
            details={"required_tool_calls": False, "resolution": False},
        ),
        tool_call_accuracy=MetricResult(
            name="tool_call_accuracy", score=1.0, passed=None, details={}
        ),
        efficiency=MetricResult(name="efficiency", score=0.5, passed=None, details={}),
        groundedness=MetricResult(
            name="groundedness",
            score=0.0,
            passed=False,
            details={
                "verdict": "not_grounded",
                "rationale": "no tool call ever confirmed a refund",
            },
        ),
        transcript=transcript,
    )


def _suite_report() -> SuiteReport:
    return SuiteReport(
        scenario_results=[
            ScenarioResult(
                scenario_id="billing_1",
                task_completion=MetricResult(
                    name="task_completion", score=1.0, passed=True, details={}
                ),
                tool_call_accuracy=MetricResult(
                    name="tool_call_accuracy", score=1.0, passed=True, details={}
                ),
                efficiency=MetricResult(
                    name="efficiency",
                    score=1.0,
                    passed=None,
                    details={"cost_usd": 0.01, "prompt_tokens": 100, "completion_tokens": 50},
                ),
            ),
        ],
        task_completion_rate=0.5,
        tool_call_accuracy_mean=1.0,
        groundedness_mean=0.5,
        cost_per_resolved_task=0.02,
        total_tokens=150,
        total_cost_usd=0.01,
    )


def test_generate_renders_both_templates_without_error(tmp_path):
    gate = GateResult(
        passed=False,
        violations=[
            Violation(
                metric="task_completion_rate",
                baseline=0.85,
                current=0.5,
                delta=0.35,
                threshold=0.05,
            )
        ],
        skipped=["groundedness_mean"],
    )
    baseline = {"metrics": {"task_completion_rate": 0.85, "tool_call_accuracy_mean": 0.9}}
    rows = [_passing_row(), _failing_row()]

    generate(
        _suite_report(), gate, baseline, rows, tmp_path, suite_name="support", model="llama3.2:3b"
    )

    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert "support" in md
    assert "FAILING: order_status_1" in md
    assert "no tool call ever confirmed a refund" in md

    assert "support" in html
    assert "FAILING: order_status_1" in html
    assert "<table>" in html


def test_generate_with_no_baseline_and_no_failures(tmp_path):
    gate = GateResult(
        passed=True, violations=[], skipped=["groundedness_mean", "cost_per_resolved_task"]
    )
    rows = [_passing_row()]

    generate(_suite_report(), gate, None, rows, tmp_path, suite_name="support", model="llama3.2:3b")

    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "FAILING" not in md
