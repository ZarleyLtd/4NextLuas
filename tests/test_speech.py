from datetime import datetime, timedelta

from src.common.gtfs_time import DUBLIN
from src.common.models import Prediction
from src.common.speech import humanise, next_trams_speech

NOW = datetime(2026, 10, 6, 20, 0, tzinfo=DUBLIN)


def pred(route, head, mins, realtime=True):
    when = NOW + timedelta(minutes=mins)
    return Prediction(route, head, when, when, realtime, 0, f"t-{route}-{mins}")


def test_humanise_expands_abbreviations():
    assert humanise("Fairfield Rd") == "Fairfield Road"


def test_speech_lists_trams_without_line_names():
    text = next_trams_speech(
        "Dundrum",
        [pred("Green", "Broombridge", 4), pred("Green", "Parnell", 7)],
        NOW,
    )
    assert text == "At Dundrum: Tram in 4 minutes to Broombridge, then in 7 minutes to Parnell."
    assert "Green" not in text
    assert "Red" not in text
    assert "Line" not in text


def test_minutes_round_half_up_not_truncate():
    p = pred("Green", "Brides Glen", 0)
    p.predicted = NOW + timedelta(seconds=29)
    assert p.minutes_from(NOW) == 0
    p.predicted = NOW + timedelta(seconds=30)
    assert p.minutes_from(NOW) == 1
    p.predicted = NOW + timedelta(minutes=18, seconds=50)
    assert p.minutes_from(NOW) == 19
    assert next_trams_speech("Dawson", [p], NOW) == "At Dawson: Tram in 19 minutes to Brides Glen."


def test_speech_due_now_and_scheduled():
    text = next_trams_speech("X", [pred("Green", "Broombridge", 0), pred("Green", "Broombridge", 12, realtime=False)], NOW)
    assert text == "At X: Tram due now to Broombridge, then scheduled in 12 minutes."


def test_speech_omits_repeated_destination():
    text = next_trams_speech(
        "Broadstone DIT",
        [
            pred("Green", "Brides Glen", 12),
            pred("Green", "Brides Glen", 27, realtime=False),
            pred("Green", "Brides Glen", 42, realtime=False),
        ],
        NOW,
    )
    assert text == (
        "At Broadstone DIT: Tram in 12 minutes to Brides Glen, "
        "then scheduled in 27 minutes, then scheduled in 42 minutes."
    )


def test_speech_names_destination_when_it_changes_again():
    text = next_trams_speech(
        "Belgard",
        [
            pred("Red", "Tallaght", 4),
            pred("Red", "Saggart", 9),
            pred("Red", "Saggart", 14),
        ],
        NOW,
    )
    assert text == "At Belgard: Tram in 4 minutes to Tallaght, then in 9 minutes to Saggart, then in 14 minutes."


def test_speech_empty_and_no_realtime():
    assert next_trams_speech("Dundrum", [], NOW).startswith("I can't find any trams due at Dundrum")
    text = next_trams_speech("X", [pred("Green", "Broombridge", 3, realtime=False)], NOW, realtime_available=False)
    assert text.startswith("At X: Tram scheduled in 3 minutes to Broombridge.")
    assert text.endswith("Live times are unavailable right now, so these are timetable times.")
