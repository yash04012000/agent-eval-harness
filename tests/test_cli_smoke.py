"""The one full-stack test in the repo (PRD 5): invokes `agent-eval run` as a real subprocess in
replay mode against the schema-smoke suite, using the committed cache. A wiring mistake between
any two PRDs surfaces here even if every unit test upstream passes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_cli_run_replay_mode_produces_reports(tmp_path):
    out_dir = tmp_path / "results"
    result = subprocess.run(
        [
            sys.executable,
            "cli.py",
            "run",
            "--suite",
            "suites/_schema_smoke_suite.yaml",
            "--mode",
            "replay",
            "--cache-dir",
            "cache",
            "--out",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode in (0, 1), result.stderr
    assert (out_dir / "report.md").exists()
    assert (out_dir / "report.html").exists()
    assert "task_completion_rate=" in result.stdout
    assert "gate:" in result.stdout
