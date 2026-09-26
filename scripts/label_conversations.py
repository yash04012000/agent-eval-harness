#!/usr/bin/env python
"""Blind human labeling for the PRD 4 judge-validation study.

Usage: python scripts/label_conversations.py [validation_dir] [labels_csv]

For each transcript under `validation_dir` (in random order, judge verdict hidden), prints the
conversation and tool calls, asks for a verdict, and appends the result to `labels_csv`. Labeling
happens blind to the judge's own verdict to avoid anchoring the human label on the thing being
validated. Safe to interrupt and resume -- already-labeled transcript ids are skipped.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from harness.transcript import Transcript, final_message

VALID_VERDICTS = {"grounded", "partial", "not_grounded"}
FIELDNAMES = ["transcript_id", "human_verdict", "notes", "labeled_at"]


def already_labeled(labels_csv: Path) -> set[str]:
    if not labels_csv.exists():
        return set()
    with labels_csv.open(newline="", encoding="utf-8") as f:
        return {row["transcript_id"] for row in csv.DictReader(f)}


def append_label(labels_csv: Path, transcript_id: str, verdict: str, notes: str = "") -> None:
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid verdict {verdict!r}, must be one of {VALID_VERDICTS}")
    is_new_file = not labels_csv.exists()
    labels_csv.parent.mkdir(parents=True, exist_ok=True)
    with labels_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new_file:
            writer.writeheader()
        writer.writerow(
            {
                "transcript_id": transcript_id,
                "human_verdict": verdict,
                "notes": notes,
                "labeled_at": datetime.now(UTC).isoformat(),
            }
        )


def format_conversation(record: dict) -> str:
    transcript = Transcript.model_validate(record["transcript"])
    lines = [
        "=" * 70,
        f"scenario: {record['scenario_id']}  (seed {record['seed']})",
        "=" * 70,
    ]
    for turn in transcript.turns:
        for call in turn.tool_calls:
            result = call.response if call.response is not None else {"error": call.error}
            lines.append(f"  [tool] {call.name}({call.arguments}) -> {result}")
        lines.append(f"  [agent] {turn.agent_message}")
    lines.append("")
    lines.append(f"Final message under audit:\n  {final_message(transcript)}")
    return "\n".join(lines)


def main(
    validation_dir: str = "data/validation_transcripts",
    labels_csv: str = "data/human_labels.csv",
) -> int:
    records = sorted(Path(validation_dir).glob("*.json"))
    if not records:
        print(f"no validation transcripts found under {validation_dir}/")
        return 1

    csv_path = Path(labels_csv)
    done = already_labeled(csv_path)
    order = list(records)
    random.shuffle(order)

    remaining = 0
    for path in order:
        record = json.loads(path.read_text(encoding="utf-8"))
        transcript_id = record["transcript_id"]
        if transcript_id in done:
            continue
        remaining += 1
        print(f"\n{format_conversation(record)}\n")
        verdict = ""
        while verdict not in VALID_VERDICTS:
            verdict = input("verdict [grounded/partial/not_grounded] (q to quit): ").strip()
            if verdict == "q":
                print(f"stopped; {len(done)} labeled so far")
                return 0
        notes = input("notes (optional): ").strip()
        append_label(csv_path, transcript_id, verdict, notes)
        done.add(transcript_id)

    print(f"\nall {len(records)} transcripts labeled")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
