from datetime import datetime, timedelta

from src.common.gtfs_time import DUBLIN
from src.common.models import Prediction
from src.common.speech import humanise, next_trams_speech, say_route

NOW = datetime(2026, 10, 6, 20, 0, tzinfo=DUBLIN)


def pred(route, head, mins, realtime=True):
    when = NOW + timedelta(minutes=mins)
    return Prediction(route, head, when, when, realtime, 0, f"t-{route}-{mins}")


def test_humanise_expands_abbreviations():
    assert humanise("Fairfield Rd") == "Fairfield Road"


def test_say_route_green_red_line():
    assert say_route("Green") == "Green Line"
    assert say_route("Red") == "Red Line"
    assert say_route("46A") == "46 A"


def test_speech_basic():
    text = next_trams_speech(
        "Dundrum, northbound towards Broombridge",
        [pred("Green", "Broombridge", 4), pred("Green", "Parnell", 7)],
        NOW,
    )
    assert text == ("At Dundrum, northbound towards Broombridge: the Green Line towards Broombridge in 4 minutes, "
                    "and the Green Line towards Parnell in 7 minutes.")


def test_speech_due_now_and_scheduled():
    text = next_trams_speech("X", [pred("Green", "Broombridge", 0), pred("Green", "Broombridge", 12, realtime=False)], NOW)
    assert "the Green Line towards Broombridge due now" in text
    assert "the Green Line scheduled in 12 minutes" in text


def test_speech_empty_and_no_realtime():
    assert next_trams_speech("Dundrum", [], NOW).startswith("I can't find any trams due at Dundrum")
    text = next_trams_speech("X", [pred("Green", "Broombridge", 3, realtime=False)], NOW, realtime_available=False)
    assert text.endswith("Live times are unavailable right now, so these are timetable times.")
