"""Application service used by the Alexa handlers. Holds per-container caches."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.common.gtfs_time import now_dublin
from src.common.models import Prediction, ServiceCalendar
from src.common.predictions import predict, select_for_speech
from src.common.rt_cache import RealtimeCache
from src.common.speech import humanise, next_trams_speech
from src.common.stations import (
    Platform, Station, bad_direction_speech, catalog_from_dicts, find_station,
    match_platforms, options_speech, split_station_and_direction, spoken_name,
)
from src.common.store import Store

log = logging.getLogger(__name__)

META_TTL_SECONDS = 60 * 60


@dataclass
class StopRef:
    stop_id: str
    stop_code: str
    stop_name: str
    label: str = ""

    @property
    def spoken_name(self) -> str:
        return self.label or humanise(self.stop_name)


@dataclass
class NextTramsResult:
    speech: str
    card_title: str
    card_text: str
    predictions: list[Prediction]
    realtime_status: str


@dataclass
class ResolveResult:
    """Result of matching a spoken station (+ optional direction) to one platform."""
    status: str   # ok | unknown_station | need_station | need_direction | bad_direction
    ref: StopRef | None = None
    prompt: str = ""
    elicit: str | None = None   # "station" | "direction" | None


class TimetableNotLoaded(RuntimeError):
    """The ingest job has not populated the table yet."""


class LuasService:
    def __init__(self, store: Store, realtime: RealtimeCache):
        self.store = store
        self.realtime = realtime
        self._stations: list[Station] | None = None
        self._calendar: ServiceCalendar | None = None
        self._meta_loaded = 0.0

    def _ensure_meta(self) -> None:
        if self._stations is not None and time.time() - self._meta_loaded < META_TTL_SECONDS:
            return
        t0 = time.perf_counter()
        rows = self.store.get_stations()
        calendar = self.store.get_calendar()
        if not rows or not calendar:
            raise TimetableNotLoaded("STATIONS/CALENDAR missing; run the ingest job")
        self._stations, self._calendar = catalog_from_dicts(rows), calendar
        self._meta_loaded = time.time()
        log.info("loaded %d stations and %d calendar days in %.2fs",
                 len(self._stations), len(self._calendar), time.perf_counter() - t0)

    def platform_ref(self, platform: Platform) -> StopRef:
        return StopRef(platform.stop_id, platform.stop_code, platform.stop_name, platform.label)

    def resolve(self, station_text: str | None, direction_text: str | None) -> ResolveResult:
        self._ensure_meta()
        if not station_text:
            return ResolveResult("need_station", prompt="Which tram stop?", elicit="station")
        station_name, direction = split_station_and_direction(station_text, direction_text)
        station = find_station(self._stations, station_name)
        if not station:
            return ResolveResult(
                "unknown_station",
                prompt=f"I don't know a tram stop called {station_text}. Try the stop name, for example Dundrum.",
            )
        matches = match_platforms(station, direction)
        usable = station.usable_platforms()
        if direction and not matches:
            return ResolveResult(
                "bad_direction",
                prompt=bad_direction_speech(station, direction),
                elicit="direction",
            )
        if not direction and len(usable) > 1:
            return ResolveResult(
                "need_direction",
                prompt=options_speech(station),
                elicit="direction",
            )
        chosen = matches[0] if matches else usable[0]
        return ResolveResult("ok", ref=self.platform_ref(chosen))

    def ref_from_stop_id(self, stop_id: str) -> StopRef | None:
        self._ensure_meta()
        for st in self._stations:
            for p in st.platforms:
                if p.stop_id == stop_id:
                    return self.platform_ref(p)
        return None

    def next_trams(self, ref: StopRef) -> NextTramsResult:
        self._ensure_meta()
        now = now_dublin()
        t0 = time.perf_counter()
        stop = self.store.get_stop(ref.stop_id)
        if stop is None:
            raise TimetableNotLoaded(f"no timetable item for {ref.stop_id}")
        rt = self.realtime.get(int(now.timestamp()))
        preds = predict(stop, self._calendar, rt.feed, now)
        chosen = select_for_speech(preds, now)
        log.info("stop %s: %d upcoming, %d chosen, realtime=%s(age %ss), %.2fs",
                 ref.stop_id, len(preds), len(chosen), rt.status, rt.age_seconds, time.perf_counter() - t0)
        label = spoken_name(ref.stop_name)
        speech = next_trams_speech(label, chosen, now, realtime_available=rt.feed is not None)
        lines = []
        for p in chosen:
            mins = p.minutes_from(now)
            when = "Due" if mins <= 0 else f"{mins} min"
            dest = humanise(p.headsign) if p.headsign else ""
            extra = "" if p.realtime else " (timetable)"
            lines.append(f"{dest:<26} {when}{extra}".strip())
        card_text = "\n".join(lines) if lines else "No trams due in the next two hours."
        if rt.feed is None:
            card_text += "\n\nLive times unavailable; showing timetable."
        return NextTramsResult(speech, label, card_text, chosen, rt.status)

    def get_favourite(self, user_id: str) -> StopRef | None:
        fav = self.store.get_favourite(user_id)
        if not fav:
            return None
        ref = self.ref_from_stop_id(fav["stop_id"])
        if ref:
            return ref
        return StopRef(fav["stop_id"], fav["stop_code"], fav["stop_name"], fav["stop_name"])

    def set_favourite(self, user_id: str, ref: StopRef) -> None:
        self.store.set_favourite(user_id, ref.stop_id, ref.stop_code, ref.stop_name)
