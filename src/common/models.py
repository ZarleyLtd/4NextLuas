"""Plain data structures shared between ingest, PoC and the skill Lambda."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Departure:
    """One scheduled departure from a stop (static timetable)."""

    trip_id: str
    route: str          # route_short_name, e.g. "46A"
    headsign: str       # trip_headsign, e.g. "Phoenix Park"
    seconds: int        # GTFS seconds since service-day midnight
    service_id: str
    stop_sequence: int

    def to_row(self) -> list:
        return [self.trip_id, self.route, self.headsign, self.seconds, self.service_id, self.stop_sequence]

    @classmethod
    def from_row(cls, row: list) -> "Departure":
        return cls(row[0], row[1], row[2], int(row[3]), row[4], int(row[5]))


@dataclass
class StopTimetable:
    stop_id: str
    stop_code: str
    stop_name: str
    departures: list[Departure] = field(default_factory=list)   # sorted by seconds

    def to_dict(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "stop_code": self.stop_code,
            "stop_name": self.stop_name,
            "departures": [d.to_row() for d in self.departures],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StopTimetable":
        return cls(
            stop_id=d["stop_id"],
            stop_code=d["stop_code"],
            stop_name=d["stop_name"],
            departures=[Departure.from_row(r) for r in d.get("departures", [])],
        )


# date "YYYYMMDD" -> set of service_ids active on that service day
ServiceCalendar = dict[str, set[str]]


@dataclass(frozen=True)
class StopTimeUpdate:
    stop_sequence: int | None
    stop_id: str | None
    arrival_delay: int | None
    arrival_time: int | None      # POSIX seconds
    departure_delay: int | None
    departure_time: int | None    # POSIX seconds
    relationship: str             # SCHEDULED | SKIPPED | NO_DATA | UNSCHEDULED


@dataclass
class TripUpdate:
    trip_id: str
    route_id: str
    relationship: str             # SCHEDULED | CANCELED | ADDED | ...
    updates: list[StopTimeUpdate] # sorted by stop_sequence when available


@dataclass
class RealtimeFeed:
    fetched_at: datetime          # when we fetched it (UTC)
    feed_timestamp: int | None    # header.timestamp (POSIX)
    trips: dict[str, TripUpdate]  # trip_id -> update
    entity_count: int = 0
    raw_bytes: int = 0


@dataclass
class Prediction:
    route: str
    headsign: str
    scheduled: datetime
    predicted: datetime
    realtime: bool                # True if a realtime update informed this prediction
    delay_seconds: int
    trip_id: str

    def minutes_from(self, now: datetime) -> int:
        """Whole minutes until departure, rounded half up. Under 30s (or past) is 0."""
        secs = (self.predicted - now).total_seconds()
        if secs <= 0:
            return 0
        return int((secs + 30) // 60)
