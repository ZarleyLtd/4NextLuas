"""Turn predictions into something pleasant for Alexa to say."""
from __future__ import annotations

import re
from datetime import datetime

from .models import Prediction

_ABBREV = {
    r"\bRd\b": "Road", r"\bSt\b": "Street", r"\bAve\b": "Avenue", r"\bSq\b": "Square",
    r"\bPk\b": "Park", r"\bStn\b": "Station", r"\bTce\b": "Terrace", r"\bCres\b": "Crescent",
    r"\bDr\b": "Drive", r"\bGdns\b": "Gardens", r"\bLwr\b": "Lower", r"\bUpr\b": "Upper",
    r"\bNth\b": "North", r"\bSth\b": "South", r"\bBr\b": "Bridge", r"\bCtr\b": "Centre",
    r"\bHosp\b": "Hospital", r"\bUni\b": "University",
}


def humanise(text: str) -> str:
    out = text.replace("�", "")
    for pat, rep in _ABBREV.items():
        out = re.sub(pat, rep, out)
    return out.strip()


def say_minutes(p: Prediction, now: datetime) -> str:
    mins = p.minutes_from(now)
    if mins <= 0:
        return "due now"
    if mins == 1:
        return "in 1 minute"
    return f"in {mins} minutes"


def _tram_clause(p: Prediction, now: datetime, lead: bool, dest: str) -> str:
    when = say_minutes(p, now)
    if not p.realtime:
        when = f"scheduled {when}" if when != "due now" else "scheduled now"
    prefix = "Tram " if lead else "then "
    if dest:
        return f"{prefix}{when} to {dest}"
    return f"{prefix}{when}"


def next_trams_speech(stop_label: str, preds: list[Prediction], now: datetime,
                      realtime_available: bool = True) -> str:
    if not preds:
        return f"I can't find any trams due at {stop_label} in the next two hours."
    parts = []
    prev_dest = None
    for i, p in enumerate(preds):
        dest = humanise(p.headsign) if p.headsign else ""
        named = dest if dest and dest != prev_dest else ""
        parts.append(_tram_clause(p, now, lead=(i == 0), dest=named))
        if dest:
            prev_dest = dest
    text = f"At {stop_label}: " + ", ".join(parts) + "."
    if not realtime_available:
        text += " Live times are unavailable right now, so these are timetable times."
    return text
