"""Join the static timetable for a stop with realtime trip updates.

GTFS-Realtime rules applied here:
- A trip whose schedule_relationship is CANCELED/DELETED is dropped.
- A StopTimeUpdate for our stop with relationship SKIPPED drops that departure.
- The delay in a StopTimeUpdate applies to that stop and all following stops until the
  next StopTimeUpdate, so if there is no update for our stop we use the nearest
  preceding one (by stop_sequence).
- If an absolute `time` is given for our stop it wins over `delay`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .gtfs_time import DUBLIN, SECONDS_PER_DAY, candidate_service_days, departure_datetime, yyyymmdd
from .models import Departure, Prediction, RealtimeFeed, ServiceCalendar, StopTimetable, TripUpdate

# How far back/forward to consider scheduled departures.
LOOKBACK = timedelta(minutes=2)       # a bus "due" a moment ago may still be arriving
LOOKAHEAD = timedelta(minutes=120)

# Selection rule for what gets spoken.
WINDOW_MINUTES = 10
MIN_RESULTS = 3
MAX_RESULTS = 8


def _active_departures(stop: StopTimetable, calendar: ServiceCalendar, now: datetime) -> list[tuple[Departure, datetime]]:
    """Scheduled departures within the look window, with absolute datetimes."""
    out: list[tuple[Departure, datetime]] = []
    lo, hi = now - LOOKBACK, now + LOOKAHEAD
    for service_day in candidate_service_days(now):
        active = calendar.get(yyyymmdd(service_day))
        if not active:
            continue
        is_yesterday = service_day < now.astimezone(DUBLIN).date()
        for dep in stop.departures:
            if dep.service_id not in active:
                continue
            # Yesterday's service day only matters for post-midnight (>= 24:00:00) times.
            if is_yesterday and dep.seconds < SECONDS_PER_DAY:
                continue
            when = departure_datetime(service_day, dep.seconds)
            if lo <= when <= hi:
                out.append((dep, when))
    out.sort(key=lambda x: x[1])
    return out


def _apply_realtime(dep: Departure, stop_id: str, scheduled: datetime, tu: TripUpdate | None) -> Prediction | None:
    if tu is None:
        return Prediction(dep.route, dep.headsign, scheduled, scheduled, False, 0, dep.trip_id)
    if tu.relationship in ("CANCELED", "DELETED"):
        return None

    exact = None
    preceding = None
    for u in tu.updates:
        if u.stop_sequence is not None:
            matches = u.stop_sequence == dep.stop_sequence
        else:
            matches = u.stop_id == stop_id
        if matches:
            exact = u
            break
        if u.stop_sequence is not None and u.stop_sequence < dep.stop_sequence:
            preceding = u

    source = exact or preceding
    if source is None:
        # Realtime trip exists but no usable update yet (e.g. trip not started): treat as scheduled.
        return Prediction(dep.route, dep.headsign, scheduled, scheduled, False, 0, dep.trip_id)

    if exact is not None and exact.relationship == "SKIPPED":
        return None
    if source.relationship == "NO_DATA":
        return Prediction(dep.route, dep.headsign, scheduled, scheduled, False, 0, dep.trip_id)

    # Prefer departure info at our stop, then arrival; absolute time beats delay.
    if exact is not None:
        abs_time = exact.departure_time or exact.arrival_time
        if abs_time:
            predicted = datetime.fromtimestamp(abs_time, tz=timezone.utc).astimezone(scheduled.tzinfo)
            return Prediction(dep.route, dep.headsign, scheduled, predicted, True,
                              int((predicted - scheduled).total_seconds()), dep.trip_id)
    delay = _pick_delay(source)
    if delay is None:
        return Prediction(dep.route, dep.headsign, scheduled, scheduled, False, 0, dep.trip_id)
    predicted = scheduled + timedelta(seconds=delay)
    return Prediction(dep.route, dep.headsign, scheduled, predicted, True, delay, dep.trip_id)


def _pick_delay(u) -> int | None:
    if u.departure_delay is not None:
        return u.departure_delay
    if u.arrival_delay is not None:
        return u.arrival_delay
    return None


def predict(stop: StopTimetable, calendar: ServiceCalendar, feed: RealtimeFeed | None, now: datetime) -> list[Prediction]:
    """All upcoming predictions for the stop, soonest first (not yet trimmed for speech)."""
    trips = feed.trips if feed else {}
    preds: list[Prediction] = []
    for dep, scheduled in _active_departures(stop, calendar, now):
        p = _apply_realtime(dep, stop.stop_id, scheduled, trips.get(dep.trip_id))
        if p is None:
            continue
        if p.predicted < now - LOOKBACK:
            continue
        preds.append(p)
    preds.sort(key=lambda p: p.predicted)
    return preds


def select_for_speech(preds: list[Prediction], now: datetime,
                      window_minutes: int = WINDOW_MINUTES,
                      min_results: int = MIN_RESULTS,
                      max_results: int = MAX_RESULTS) -> list[Prediction]:
    """Everything due within `window_minutes`, but at least `min_results`, at most `max_results`."""
    cutoff = now + timedelta(minutes=window_minutes)
    within = [p for p in preds if p.predicted <= cutoff]
    if len(within) < min_results:
        return preds[:min_results]
    return within[:max_results]
