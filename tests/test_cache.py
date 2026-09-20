import pytest

from harness.cache import CachedModelClient, CacheMiss, CacheMode, cache_key
from harness.model_client import ModelResponse


class _FakeInnerClient:
    def __init__(self, response: ModelResponse):
        self._response = response
        self.call_count = 0

    async def complete(self, model, messages, tools=None, temperature=0.0, **kwargs):
        self.call_count += 1
        return self._response


def _fixed_response(**overrides) -> ModelResponse:
    base = dict(
        content="hello",
        tool_calls=[],
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1.0,
        raw={},
    )
    base.update(overrides)
    return ModelResponse(**base)


def test_cache_key_stable_regardless_of_dict_key_order():
    messages = [{"role": "user", "content": "hi"}]
    key_a = cache_key("m", messages, [{"a": 1, "b": 2}], 0.0)
    key_b = cache_key("m", messages, [{"b": 2, "a": 1}], 0.0)
    assert key_a == key_b


def test_cache_key_differs_on_temperature():
    messages = [{"role": "user", "content": "hi"}]
    assert cache_key("m", messages, None, 0.0) != cache_key("m", messages, None, 0.7)


async def test_record_mode_writes_cache_and_calls_inner(tmp_path):
    inner = _FakeInnerClient(_fixed_response())
    client = CachedModelClient(inner, cache_dir=tmp_path, mode=CacheMode.RECORD)
    messages = [{"role": "user", "content": "hi"}]

    response = await client.complete(model="gpt-4o-mini", messages=messages)

    assert inner.call_count == 1
    assert response.content == "hello"
    assert len(list(tmp_path.glob("*.json"))) == 1


async def test_replay_mode_hits_cache_without_calling_inner(tmp_path):
    inner = _FakeInnerClient(_fixed_response())
    messages = [{"role": "user", "content": "hi"}]

    recorder = CachedModelClient(inner, cache_dir=tmp_path, mode=CacheMode.RECORD)
    await recorder.complete(model="gpt-4o-mini", messages=messages)
    assert inner.call_count == 1

    replayer = CachedModelClient(inner, cache_dir=tmp_path, mode=CacheMode.REPLAY)
    response = await replayer.complete(model="gpt-4o-mini", messages=messages)

    assert inner.call_count == 1  # no additional call made
    assert response.content == "hello"


async def test_replay_mode_miss_raises_without_calling_inner(tmp_path):
    inner = _FakeInnerClient(_fixed_response())
    client = CachedModelClient(inner, cache_dir=tmp_path, mode=CacheMode.REPLAY)

    with pytest.raises(CacheMiss):
        await client.complete(model="gpt-4o-mini", messages=[{"role": "user", "content": "new"}])

    assert inner.call_count == 0


async def test_on_usage_called_only_on_non_cached_response(tmp_path):
    inner = _FakeInnerClient(_fixed_response())
    usage_calls = []
    on_usage = lambda p, c: usage_calls.append((p, c))  # noqa: E731
    messages = [{"role": "user", "content": "hi"}]

    recorder = CachedModelClient(
        inner, cache_dir=tmp_path, mode=CacheMode.RECORD, on_usage=on_usage
    )
    await recorder.complete(model="gpt-4o-mini", messages=messages)
    assert usage_calls == [(10, 5)]

    replayer = CachedModelClient(
        inner, cache_dir=tmp_path, mode=CacheMode.REPLAY, on_usage=on_usage
    )
    await replayer.complete(model="gpt-4o-mini", messages=messages)
    assert usage_calls == [(10, 5)]  # unchanged -- cache hit never calls on_usage


async def test_live_mode_bypasses_cache_entirely(tmp_path):
    inner = _FakeInnerClient(_fixed_response())
    client = CachedModelClient(inner, cache_dir=tmp_path, mode=CacheMode.LIVE)
    messages = [{"role": "user", "content": "hi"}]

    await client.complete(model="gpt-4o-mini", messages=messages)
    await client.complete(model="gpt-4o-mini", messages=messages)

    assert inner.call_count == 2
    assert list(tmp_path.glob("*.json")) == []
