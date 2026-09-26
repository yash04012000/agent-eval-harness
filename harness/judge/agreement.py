"""Judge/human agreement statistics for the PRD 4 validation study.

Kappa, not raw agreement alone, is the headline number: raw agreement is inflated by however
skewed the label distribution is (a judge that always says "grounded" looks accurate on a set
that's mostly grounded while being useless). Landis & Koch's convention (kappa >= 0.6,
"substantial") is the documented bar for treating the judge as trustworthy enough to gate on.
"""

from __future__ import annotations

from collections import Counter


def confusion_matrix(
    human: list[str], judge: list[str], categories: list[str]
) -> dict[str, dict[str, int]]:
    matrix = {h: dict.fromkeys(categories, 0) for h in categories}
    for h, j in zip(human, judge, strict=True):
        matrix[h][j] += 1
    return matrix


def cohens_kappa(human: list[str], judge: list[str], categories: list[str]) -> float:
    n = len(human)
    if n == 0:
        return 0.0

    matrix = confusion_matrix(human, judge, categories)
    observed_agreement = sum(matrix[c][c] for c in categories) / n

    human_counts = Counter(human)
    judge_counts = Counter(judge)
    expected_agreement = sum(
        (human_counts.get(c, 0) / n) * (judge_counts.get(c, 0) / n) for c in categories
    )

    if expected_agreement == 1.0:
        return 1.0
    return (observed_agreement - expected_agreement) / (1 - expected_agreement)
