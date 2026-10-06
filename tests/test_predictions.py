from datetime import datetime, timedelta, timezone

from src.common.gtfs_time import DUBLIN, parse_gtfs_time, format_gtfs_time
from src.common.models import Departure, RealtimeFeed, StopTimeUpdate, StopTimetable, TripUpdate
from src.common.predictions import predict, select_for_speech

STOP = "8220DB000184"


def dep(trip, route, secs, service="S1", seq=10, headsign="Town"):
    return Departure(trip, route, headsign, secs, service, seq)


def stop_with(*deps):
    return StopTimetable(STOP, "184", "Fairfield Rd", sorted(deps, key=lambda d: d.seconds))


def feed(*trips: TripUpdate):
    return RealtimeFeed(datetime.now(timezone.utc), None, {t.trip_id: t for t in trips})


def stu(seq=10, stop_id=STOP, dep_delay=None, arr_delay=None, arr_time=None, dep_time=None, rel="SCHEDULED"):
    return StopTimeUpdate(seq, stop_id, arr_delay, arr_time, dep_delay, dep_time, rel)


def at(h, m, day=(2026, 10, 3)):
    return datetime(*day, h, m, tzinfo=DUBLIN)


CAL = {"20261002": {"S1"}, "20261003": {"S1"}, "20261004": {"S1"}}


def test_gtfs_time_roundtrip():
    assert parse_gtfs_time("25:10:30") == 90630
    assert format_gtfs_time(90630) == "25:10:30"


def test_scheduled_only_when_no_feed():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00")))
    preds = predict(stop, CAL, None, at(20, 6))
    assert len(preds) == 1
    assert preds[0].realtime is False
    assert preds[0].predicted == at(20, 13)


def test_inactive_service_is_ignored():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00"), service="S9"))
    assert predict(stop, CAL, None, at(20, 6)) == []


def test_delay_applied_at_exact_stop():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00")))
    f = feed(TripUpdate("t1", "r", "SCHEDULED", [stu(seq=10, dep_delay=345)]))
    p = predict(stop, CAL, f, at(20, 6))[0]
    assert p.realtime and p.delay_seconds == 345
    assert p.predicted == at(20, 13) + timedelta(seconds=345)


def test_delay_propagates_from_preceding_stop():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00"), seq=10))
    f = feed(TripUpdate("t1", "r", "SCHEDULED", [stu(seq=4, dep_delay=120), stu(seq=15, dep_delay=600)]))
    p = predict(stop, CAL, f, at(20, 6))[0]
    assert p.delay_seconds == 120


def test_absolute_time_beats_delay():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00")))
    target = at(20, 20)
    f = feed(TripUpdate("t1", "r", "SCHEDULED", [stu(seq=10, dep_delay=60, arr_time=int(target.timestamp()))]))
    p = predict(stop, CAL, f, at(20, 6))[0]
    assert p.predicted == target


def test_cancelled_trip_dropped():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00")))
    f = feed(TripUpdate("t1", "r", "CANCELED", []))
    assert predict(stop, CAL, f, at(20, 6)) == []


def test_skipped_stop_dropped():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:13:00")))
    f = feed(TripUpdate("t1", "r", "SCHEDULED", [stu(seq=10, rel="SKIPPED")]))
    assert predict(stop, CAL, f, at(20, 6)) == []


def test_post_midnight_trip_uses_yesterdays_service_day():
    # 25:30 on service day 2 Oct == 01:30 on 3 Oct. Only S_FRI runs on the 2nd.
    cal = {"20261002": {"S_FRI"}, "20261003": {"S_SAT"}}
    stop = stop_with(dep("t1", "N1", parse_gtfs_time("25:30:00"), service="S_FRI"),
                     dep("t2", "N2", parse_gtfs_time("01:30:00"), service="S_FRI"))  # not today's service
    preds = predict(stop, cal, None, at(1, 20))
    assert [p.route for p in preds] == ["N1"]
    assert preds[0].predicted == at(1, 30)


def test_departed_buses_are_dropped_but_due_is_kept():
    stop = stop_with(dep("t1", "23", parse_gtfs_time("20:00:00")),
                     dep("t2", "24", parse_gtfs_time("20:05:30")))
    preds = predict(stop, CAL, None, at(20, 6))
    assert [p.route for p in preds] == ["24"]
    assert preds[0].minutes_from(at(20, 6)) <= 0


def test_selection_window_with_minimum():
    now = at(20, 0)
    stop = stop_with(*[dep(f"t{i}", str(i), parse_gtfs_time("20:00:00") + i * 60 * 7) for i in range(1, 6)])
    # departures at +7, +14, +21, +28, +35 minutes
    preds = predict(stop, CAL, None, now)
    chosen = select_for_speech(preds, now)
    assert [p.route for p in chosen] == ["1", "2", "3"]      # only 1 within 10 min, so min 3 applies


def test_selection_window_takes_all_within_window_up_to_max():
    now = at(20, 0)
    stop = stop_with(*[dep(f"t{i}", str(i), parse_gtfs_time("20:00:00") + i * 60) for i in range(1, 12)])
    chosen = select_for_speech(predict(stop, CAL, None, now), now)
    assert len(chosen) == 8                                   # 9 within 10 min, capped at 8
