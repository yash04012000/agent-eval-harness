"""Shared token budget across a whole run (PRD 2).

A single `TokenBudgetTracker` is handed to `CachedModelClient` as its `on_usage` callback, so
every non-cached call -- agent, simulated user, and later the judge -- counts against the same
total. No `await` happens inside `add`, so a plain counter is safe under asyncio's cooperative
concurrency without a lock.
"""

from __future__ import annotations


class BudgetExceeded(Exception):
    def __init__(self, limit: int, used: int):
        super().__init__(f"token budget exceeded: used {used} of {limit}")
        self.limit = limit
        self.used = used


class TokenBudgetTracker:
    def __init__(self, limit: int | None):
        self._limit = limit
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        self._used += prompt_tokens + completion_tokens
        if self._limit is not None and self._used > self._limit:
            raise BudgetExceeded(self._limit, self._used)
