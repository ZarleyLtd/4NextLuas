from datetime import datetime, timezone

import pytest

from src.common import rt_cache
from src.common.models import RealtimeFeed
from src.common.realtime import RealtimeError
from src.common.rt_cache import RealtimeCache


class FakeStore:
    """Mimics the conditional-write lock semantics of Store.try_acquire_rt_lock."""

    def __init__(self):
        self.last_fetch = None

    def try_acquire_rt_lock(self, now_epoch, min_interval=60):
        if self.last_fetch is None or self.last_fetch <= now_epoch - min_interval:
            self.last_fetch = now_epoch
            return True
        return False


def make_feed():
    return RealtimeFeed(datetime.now(timezone.utc), None, {}, entity_count=1)


@pytest.fixture
def fetches(monkeypatch):
    calls = []

    def fake_fetch(api_key, **kw):
        calls.append(api_key)
        return make_feed()

    monkeypatch.setattr(rt_cache, "fetch_trip_updates", fake_fetch)
    return calls


def test_first_call_fetches_then_caches(fetches):
    cache = RealtimeCache(FakeStore(), "k")
    r1 = cache.get(now_epoch=1000)
    r2 = cache.get(now_epoch=1030)
    assert (r1.status, r2.status) == ("fresh", "cached")
    assert len(fetches) == 1


def test_refetches_after_interval(fetches):
    cache = RealtimeCache(FakeStore(), "k")
    cache.get(now_epoch=1000)
    r = cache.get(now_epoch=1061)
    assert r.status == "fresh"
    assert len(fetches) == 2


def test_lock_held_by_other_container_serves_stale_copy(fetches):
    store = FakeStore()
    a = RealtimeCache(store, "k")
    b = RealtimeCache(store, "k")
    a.get(now_epoch=1000)                  # a fetched
    assert b.get(now_epoch=1010).status == "unavailable"   # b has nothing and cannot fetch
    assert len(fetches) == 1
    b.get(now_epoch=1070)                  # b's turn
    a.get(now_epoch=1065)                  # a's copy is 65s old but lock is b's -> stale
    r = a.get(now_epoch=1080)
    assert r.status == "stale" and r.age_seconds == 80


def test_fetch_failure_falls_back(monkeypatch):
    def boom(api_key, **kw):
        raise RealtimeError("HTTP 429", status=429)

    monkeypatch.setattr(rt_cache, "fetch_trip_updates", boom)
    cache = RealtimeCache(FakeStore(), "k")
    assert cache.get(now_epoch=1000).status == "unavailable"


def test_pack_roundtrip():
    from src.common.store import pack, unpack, content_hash
    data = {"a": [1, "x", None], "é": "ü"}
    assert unpack(pack(data)) == data
    assert content_hash(data) == content_hash({"a": [1, "x", None], "é": "ü"})


def test_rt_lock_uses_shared_table():
    from src.common.store import Store

    class RecordingClient:
        def __init__(self):
            self.calls = []

        def update_item(self, **kwargs):
            self.calls.append(kwargs)

    client = RecordingClient()
    store = Store("FourNextLuas", client=client, lock_table="FourNextBus")
    assert store.try_acquire_rt_lock(1_700_000_000) is True
    assert client.calls[0]["TableName"] == "FourNextBus"
    assert client.calls[0]["Key"] == {"pk": {"S": "META"}, "sk": {"S": "RTLOCK"}}
