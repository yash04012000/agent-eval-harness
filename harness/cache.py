"""Deterministic cache/replay for model calls (PRD 1).

Every scenario in `suites/` has its model responses committed under `cache/` so a `replay`-mode
run needs no API key and always produces the same transcript. `record` mode is the one deliberate
action that talks to a real provider and (re)writes the cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from harness.model_client import ModelClient, ModelResponse


class CacheMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"
    LIVE = "live"


class CacheMiss(Exception):
    """Raised in `replay` mode when no cached response exists for a request."""


def cache_key(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    temperature: float,
) -> str:
    """Stable hash over the parts of a request that determine its response."""
    payload = {"model": model, "messages": messages, "tools": tools, "temperature": temperature}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CacheStore:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> ModelResponse | None:
        path = self._path(key)
        if not path.exists():
            return None
        return ModelResponse.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, key: str, response: ModelResponse) -> None:
        self._path(key).write_text(response.model_dump_json(indent=2), encoding="utf-8")


class CachedModelClient:
    """Wraps a `ModelClient` with record/replay caching. Itself satisfies `ModelClient`."""

    def __init__(
        self,
        inner: ModelClient,
        cache_dir: str | Path,
        mode: CacheMode = CacheMode.REPLAY,
        on_usage: Callable[[int, int], None] | None = None,
    ):
        self._inner = inner
        self._store = CacheStore(cache_dir)
        self._mode = mode
        self._on_usage = on_usage
        self.last_cache_hit: bool | None = None  # read by harness.tracing's model_call span

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> ModelResponse:
        key = cache_key(model, messages, tools, temperature)

        if self._mode is not CacheMode.LIVE:
            cached = self._store.get(key)
            if cached is not None:
                self.last_cache_hit = True
                return cached
            if self._mode is CacheMode.REPLAY:
                self.last_cache_hit = False
                raise CacheMiss(
                    f"no cached response for key={key} model={model!r}; "
                    "run with --mode record first to populate the cache"
                )

        self.last_cache_hit = False
        response = await self._inner.complete(
            model, messages, tools=tools, temperature=temperature, **kwargs
        )

        if self._on_usage is not None:
            self._on_usage(response.prompt_tokens, response.completion_tokens)

        if self._mode is CacheMode.RECORD:
            self._store.put(key, response)

        return response
