"""GTFS time helpers.

GTFS times are "HH:MM:SS" measured from the start of the *service day*, and may exceed
24:00:00 for trips that run past midnight (the NTA feed goes up to about 32:38:00).
A departure at 25:10:00 on service day D happens at 01:10 on calendar day D+1.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DUBLIN = ZoneInfo("Europe/Dublin")
SECONDS_PER_DAY = 86_400


def parse_gtfs_time(text: str) -> int:
    """'25:10:30' -> seconds since service-day midnight (90630)."""
    h, m, s = text.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def format_gtfs_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def service_day_start(day: date) -> datetime:
    """Local midnight at the start of the given service day (tz-aware)."""
    return datetime(day.year, day.month, day.day, tzinfo=DUBLIN)


def departure_datetime(service_day: date, seconds: int) -> datetime:
    """Absolute time of a departure given its service day and GTFS seconds."""
    return service_day_start(service_day) + timedelta(seconds=seconds)


def yyyymmdd(day: date) -> str:
    return day.strftime("%Y%m%d")


def parse_yyyymmdd(text: str) -> date:
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


def now_dublin() -> datetime:
    return datetime.now(timezone.utc).astimezone(DUBLIN)


def candidate_service_days(now: datetime) -> list[date]:
    """Service days whose trips could still be running at `now`.

    Today's service day always applies. Yesterday's applies too for early-morning
    hours, because a 25:30 trip on yesterday's timetable is 01:30 today.
    """
    today = now.astimezone(DUBLIN).date()
    return [today - timedelta(days=1), today]
