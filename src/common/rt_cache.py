"""Realtime feed cache that respects NTA's one-request-per-60-seconds policy.

Lives for the lifetime of a Lambda container. Before calling NTA it claims a
DynamoDB lock item (conditional write). The lock table is shared with 4NextBus
(and later siblings) so one NTA key stays at one call per minute across skills.
A container that loses the race serves its own last copy if it has one,
otherwise the caller falls back to timetable times.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .models import RealtimeFeed
from .realtime import MIN_INTERVAL_SECONDS, RealtimeError, fetch_trip_updates
from .store import Store

log = logging.getLogger(__name__)

MAX_USABLE_AGE = 5 * 60   # serve a cached feed up to this old when we cannot refresh


@dataclass
class RealtimeResult:
    feed: RealtimeFeed | None
    status: str          # fresh | cached | stale | unavailable
    age_seconds: int


class RealtimeCache:
    def __init__(self, store: Store, api_key: str, min_interval: int = MIN_INTERVAL_SECONDS):
        self.store = store
        self.api_key = api_key
        self.min_interval = min_interval
        self.feed: RealtimeFeed | None = None
        self._fetched_epoch = 0

    def _age(self, now_epoch: int) -> int:
        return now_epoch - self._fetched_epoch if self.feed else 10**9

    def get(self, now_epoch: int | None = None) -> RealtimeResult:
        now_epoch = int(now_epoch or time.time())
        age = self._age(now_epoch)
        if self.feed is not None and age < self.min_interval:
            return RealtimeResult(self.feed, "cached", age)

        if self.store.try_acquire_rt_lock(now_epoch, self.min_interval):
            try:
                self.feed = fetch_trip_updates(self.api_key)
                self._fetched_epoch = now_epoch
                return RealtimeResult(self.feed, "fresh", 0)
            except RealtimeError as exc:
                log.warning("realtime fetch failed (%s); falling back", exc)
        else:
            log.info("realtime lock held by another caller; using cached copy if any")

        if self.feed is not None and age <= MAX_USABLE_AGE:
            return RealtimeResult(self.feed, "stale", age)
        return RealtimeResult(None, "unavailable", age)
