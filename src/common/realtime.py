"""Fetch and parse the NTA GTFS-Realtime TripUpdates feed.

Fair-use policy: one request per 60 seconds per key. Callers must enforce this
(see `RealtimeCache`); this module only does the HTTP + protobuf work.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests
from google.transit import gtfs_realtime_pb2

from .models import RealtimeFeed, StopTimeUpdate, TripUpdate

log = logging.getLogger(__name__)

TRIP_UPDATES_URL = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"
MIN_INTERVAL_SECONDS = 60

_TRIP_REL = {0: "SCHEDULED", 1: "ADDED", 2: "UNSCHEDULED", 3: "CANCELED", 5: "REPLACEMENT", 6: "DUPLICATED", 7: "DELETED"}
_STOP_REL = {0: "SCHEDULED", 1: "SKIPPED", 2: "NO_DATA", 3: "UNSCHEDULED"}


class RealtimeError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def fetch_trip_updates(api_key: str, timeout: float = 8.0, session: requests.Session | None = None) -> RealtimeFeed:
    """GET the feed as protobuf and index it by trip_id. Raises RealtimeError on failure."""
    sess = session or requests.Session()
    headers = {"x-api-key": api_key, "Accept": "application/x-protobuf", "User-Agent": "4NextTram/1.0"}
    t0 = time.perf_counter()
    try:
        resp = sess.get(TRIP_UPDATES_URL, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise RealtimeError(f"network error: {exc}") from exc
    t_fetch = time.perf_counter() - t0
    if resp.status_code != 200:
        raise RealtimeError(f"HTTP {resp.status_code}: {resp.text[:200]}", status=resp.status_code)

    t1 = time.perf_counter()
    feed = parse_feed(resp.content)
    t_parse = time.perf_counter() - t1
    log.info("realtime: %d bytes in %.2fs, parsed %d entities in %.2fs",
             len(resp.content), t_fetch, feed.entity_count, t_parse)
    return feed


def parse_feed(raw: bytes) -> RealtimeFeed:
    msg = gtfs_realtime_pb2.FeedMessage()
    msg.ParseFromString(raw)

    trips: dict[str, TripUpdate] = {}
    for entity in msg.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip = tu.trip
        updates: list[StopTimeUpdate] = []
        for stu in tu.stop_time_update:
            arr = stu.arrival if stu.HasField("arrival") else None
            dep = stu.departure if stu.HasField("departure") else None
            updates.append(StopTimeUpdate(
                stop_sequence=stu.stop_sequence if stu.HasField("stop_sequence") else None,
                stop_id=stu.stop_id or None,
                arrival_delay=arr.delay if arr is not None and arr.HasField("delay") else None,
                arrival_time=arr.time if arr is not None and arr.HasField("time") else None,
                departure_delay=dep.delay if dep is not None and dep.HasField("delay") else None,
                departure_time=dep.time if dep is not None and dep.HasField("time") else None,
                relationship=_STOP_REL.get(stu.schedule_relationship, "SCHEDULED"),
            ))
        updates.sort(key=lambda u: (u.stop_sequence is None, u.stop_sequence or 0))
        trips[trip.trip_id] = TripUpdate(
            trip_id=trip.trip_id,
            route_id=trip.route_id,
            relationship=_TRIP_REL.get(trip.schedule_relationship, "SCHEDULED"),
            updates=updates,
        )

    return RealtimeFeed(
        fetched_at=datetime.now(timezone.utc),
        feed_timestamp=msg.header.timestamp if msg.header.HasField("timestamp") else None,
        trips=trips,
        entity_count=len(msg.entity),
        raw_bytes=len(raw),
    )
