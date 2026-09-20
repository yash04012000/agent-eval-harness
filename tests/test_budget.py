import pytest

from harness.budget import BudgetExceeded, TokenBudgetTracker


def test_no_limit_never_raises():
    tracker = TokenBudgetTracker(None)
    tracker.add(10_000, 10_000)
    assert tracker.used == 20_000


def test_stays_under_limit():
    tracker = TokenBudgetTracker(100)
    tracker.add(30, 30)
    assert tracker.used == 60


def test_exceeding_limit_raises_and_reports_used():
    tracker = TokenBudgetTracker(100)
    tracker.add(50, 40)  # 90, still fine
    with pytest.raises(BudgetExceeded) as exc_info:
        tracker.add(5, 10)  # 105, over
    assert exc_info.value.limit == 100
    assert exc_info.value.used == 105
    assert tracker.used == 105  # the over-budget call still counted


def test_exactly_at_limit_does_not_raise():
    tracker = TokenBudgetTracker(100)
    tracker.add(60, 40)
    assert tracker.used == 100
