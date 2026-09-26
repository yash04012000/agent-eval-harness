#!/usr/bin/env python
"""Builds the PRD 4 judge-validation report from committed human labels + the cached judge.

Usage: python scripts/judge_validation_report.py

Replays the judge (cache mode -- no live calls) over every transcript in the validation set,
compares against `data/human_labels.csv`, and writes `results/judge_validation_report.md`: raw
agreement, Cohen's kappa, a confusion matrix, and every disagreement with both verdicts and the
judge's rationale, so a reader can audit *which kinds* of claims the judge gets wrong.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

from harness.cache import CachedModelClient, CacheMode
from harness.judge.agreement import cohens_kappa, confusion_matrix
from harness.judge.rubric import run_judge
from harness.judge.schema import JudgeVerdict
from harness.model_client import LiteLLMModelClient
from harness.scenario import load_scenario
from harness.transcript import Transcript

CATEGORIES = ["grounded", "partial", "not_grounded"]


async def _judge_verdicts(
    validation_dir: Path, judge_model: str, cache_dir: str
) -> dict[str, JudgeVerdict]:
    client = CachedModelClient(LiteLLMModelClient(), cache_dir=cache_dir, mode=CacheMode.REPLAY)
    verdicts: dict[str, JudgeVerdict] = {}
    for path in sorted(validation_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        transcript = Transcript.model_validate(record["transcript"])
        scenario = load_scenario(record["scenario_path"])
        verdicts[record["transcript_id"]] = await run_judge(
            transcript, scenario, client, judge_model
        )
    return verdicts


def build_report(
    human_labels_csv: str,
    validation_dir: str,
    judge_model: str,
    cache_dir: str = "cache",
) -> str:
    with open(human_labels_csv, newline="", encoding="utf-8") as f:
        human_rows = list(csv.DictReader(f))

    judge_verdicts = asyncio.run(_judge_verdicts(Path(validation_dir), judge_model, cache_dir))

    human: list[str] = []
    judge: list[str] = []
    rows: list[tuple[str, str, str, str]] = []
    for row in human_rows:
        transcript_id = row["transcript_id"]
        if transcript_id not in judge_verdicts:
            continue
        verdict = judge_verdicts[transcript_id]
        human.append(row["human_verdict"])
        judge.append(verdict.verdict)
        rows.append((transcript_id, row["human_verdict"], verdict.verdict, verdict.rationale))

    agreements = sum(h == j for h, j in zip(human, judge, strict=True))
    raw_agreement = agreements / len(human) if human else 0.0
    kappa = cohens_kappa(human, judge, CATEGORIES)
    matrix = confusion_matrix(human, judge, CATEGORIES)

    lines = [
        "# Judge validation report",
        "",
        f"- judge model: `{judge_model}`",
        f"- conversations labeled: {len(human)}",
        f"- raw agreement: {raw_agreement:.1%}",
        f"- Cohen's kappa: {kappa:.3f}"
        f" ({'substantial+' if kappa >= 0.6 else 'below the 0.6 substantial-agreement bar'})",
        "",
        "## Confusion matrix (rows = human, columns = judge)",
        "",
        "| human \\ judge | " + " | ".join(CATEGORIES) + " |",
        "|---|" + "---|" * len(CATEGORIES),
    ]
    for h in CATEGORIES:
        lines.append(f"| {h} | " + " | ".join(str(matrix[h][j]) for j in CATEGORIES) + " |")

    lines += ["", "## Disagreements", ""]
    disagreements = [r for r in rows if r[1] != r[2]]
    if not disagreements:
        lines.append("(none)")
    else:
        for transcript_id, h, j, rationale in disagreements:
            lines.append(
                f"- `{transcript_id}`: human=**{h}**, judge=**{j}** -- judge rationale: {rationale}"
            )

    return "\n".join(lines) + "\n"


def main(
    human_labels_csv: str = "data/human_labels.csv",
    validation_dir: str = "data/validation_transcripts",
    judge_model: str = "llama3.2:3b",
    cache_dir: str = "cache",
    out: str = "results/judge_validation_report.md",
) -> int:
    report = build_report(human_labels_csv, validation_dir, judge_model, cache_dir)
    Path(out).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
