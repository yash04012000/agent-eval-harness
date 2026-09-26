from harness.judge.agreement import cohens_kappa, confusion_matrix

CATEGORIES = ["grounded", "partial", "not_grounded"]

# Hand-built fixture: 10 labels, computed by hand (and cross-checked against
# sklearn.metrics.cohen_kappa_score during development -- not a runtime dependency).
HUMAN = ["grounded"] * 5 + ["partial"] * 3 + ["not_grounded"] * 2
JUDGE = [
    "grounded",
    "grounded",
    "grounded",
    "partial",
    "grounded",  # human=grounded (5): 4 correct, 1 called partial
    "partial",
    "partial",
    "grounded",  # human=partial (3): 2 correct, 1 called grounded
    "not_grounded",
    "not_grounded",  # human=not_grounded (2): both correct
]


def test_confusion_matrix_hand_built_fixture():
    matrix = confusion_matrix(HUMAN, JUDGE, CATEGORIES)

    assert matrix["grounded"] == {"grounded": 4, "partial": 1, "not_grounded": 0}
    assert matrix["partial"] == {"grounded": 1, "partial": 2, "not_grounded": 0}
    assert matrix["not_grounded"] == {"grounded": 0, "partial": 0, "not_grounded": 2}


def test_cohens_kappa_hand_computed_value():
    # po = (4+2+2)/10 = 0.8; pe = 0.5^2 + 0.3^2 + 0.2^2 = 0.38; kappa = (0.8-0.38)/(1-0.38)
    kappa = cohens_kappa(HUMAN, JUDGE, CATEGORIES)
    assert round(kappa, 4) == round((0.8 - 0.38) / (1 - 0.38), 4)


def test_perfect_agreement_is_kappa_one():
    labels = ["grounded", "partial", "not_grounded", "grounded"]
    assert cohens_kappa(labels, labels, CATEGORIES) == 1.0


def test_empty_input_is_zero():
    assert cohens_kappa([], [], CATEGORIES) == 0.0
