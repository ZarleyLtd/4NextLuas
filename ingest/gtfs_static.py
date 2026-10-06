"""Load the TFI static GTFS feed with DuckDB and build per-stop timetables.

Used by the local PoC and by the daily ingest job. Not used inside the Lambda.
"""
from __future__ import annotations

import logging
import os
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
import requests

from src.common.gtfs_time import parse_yyyymmdd, yyyymmdd
from src.common.models import Departure, ServiceCalendar, StopTimetable
from src.common.stations import build_station

log = logging.getLogger(__name__)

GTFS_URL = "https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip"
NEEDED = ["agency.txt", "routes.txt", "stops.txt", "trips.txt", "calendar.txt", "calendar_dates.txt", "stop_times.txt", "feed_info.txt"]

# TFI GTFS_Realtime.zip includes bus, Luas, and rail. This skill keeps tram only.
TRAM_ROUTE_TYPE = "0"


def ensure_gtfs(cache_dir: Path, max_age_hours: float = 20.0, url: str = GTFS_URL) -> Path:
    """Download the zip if missing/stale and extract the needed files. Returns the extract dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "GTFS_Realtime.zip"
    out_dir = cache_dir / "gtfs"
    stale = (not zip_path.exists()
             or (time.time() - zip_path.stat().st_mtime) > max_age_hours * 3600)
    if stale:
        log.info("downloading %s", url)
        t0 = time.perf_counter()
        with requests.get(url, stream=True, timeout=180) as resp:
            resp.raise_for_status()
            tmp = zip_path.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
        os.replace(tmp, zip_path)
        log.info("downloaded %.0f MB in %.1fs", zip_path.stat().st_size / 1e6, time.perf_counter() - t0)
        for p in out_dir.glob("*.txt"):
            p.unlink()
    if not all((out_dir / n).exists() for n in NEEDED if n != "feed_info.txt"):
        out_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            for n in NEEDED:
                if n in z.namelist():
                    z.extract(n, out_dir)
    return out_dir


class GtfsStatic:
    """Thin DuckDB wrapper over the extracted GTFS text files."""

    def __init__(self, gtfs_dir: Path):
        self.dir = gtfs_dir
        self.con = duckdb.connect()
        for name in ["agency", "routes", "stops", "trips", "calendar", "calendar_dates", "stop_times"]:
            path = (gtfs_dir / f"{name}.txt").as_posix()
            self.con.execute(
                f"create view {name} as select * from read_csv('{path}', header=true, all_varchar=true)"
            )

    # ---- lookups -------------------------------------------------------------------

    def feed_version(self) -> str:
        p = self.dir / "feed_info.txt"
        if not p.exists():
            return "unknown"
        rows = self.con.execute(
            f"select feed_version, feed_start_date from read_csv('{p.as_posix()}', header=true, all_varchar=true)"
        ).fetchall()
        return rows[0][0] if rows else "unknown"

    def stop_code_map(self, tram_only: bool = True) -> dict[str, dict]:
        """stop_code -> {"stop_id", "stop_name"}. Prefer stops that have tram departures."""
        served = "and s.stop_id in (select distinct stop_id from stop_times)" if tram_only else ""
        rows = self.con.execute(f"""
            select s.stop_code, s.stop_id, s.stop_name
            from stops s
            where s.stop_code is not null and s.stop_code <> '' {served}
            order by s.stop_code,
                     case when s.stop_id like '8220GA%' then 0
                          when s.stop_id like '82%GA%' then 1 else 2 end,
                     s.stop_id
        """).fetchall()
        out: dict[str, dict] = {}
        for code, stop_id, name in rows:
            out.setdefault(code.strip(), {"stop_id": stop_id, "stop_name": name})
        return out

    def stop_info(self, stop_id: str) -> tuple[str, str] | None:
        rows = self.con.execute("select stop_code, stop_name from stops where stop_id = ?", [stop_id]).fetchall()
        return (rows[0][0], rows[0][1]) if rows else None

    def service_calendar(self, start: date, days: int = 14) -> ServiceCalendar:
        """date 'YYYYMMDD' -> set(service_id) for each day in [start, start+days)."""
        cal = self.con.execute("select * from calendar").fetchall()
        cal_cols = [d[0] for d in self.con.description]
        exc = self.con.execute("select service_id, date, exception_type from calendar_dates").fetchall()
        weekday_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        idx = {c: i for i, c in enumerate(cal_cols)}

        result: ServiceCalendar = {}
        for d in range(days):
            day = start + timedelta(days=d)
            key = yyyymmdd(day)
            active: set[str] = set()
            for row in cal:
                sd, ed = parse_yyyymmdd(row[idx["start_date"]]), parse_yyyymmdd(row[idx["end_date"]])
                if sd <= day <= ed and row[idx[weekday_cols[day.weekday()]]] == "1":
                    active.add(row[idx["service_id"]])
            for sid, ex_date, ex_type in exc:
                if ex_date == key:
                    if ex_type == "1":
                        active.add(sid)
                    elif ex_type == "2":
                        active.discard(sid)
            result[key] = active
        return result

    def stop_timetable(self, stop_id: str) -> StopTimetable | None:
        info = self.stop_info(stop_id)
        if info is None:
            return None
        rows = self.con.execute("""
            select st.trip_id, r.route_short_name, coalesce(nullif(st.stop_headsign,''), t.trip_headsign, '') as headsign,
                   st.departure_time, t.service_id, st.stop_sequence
            from stop_times st
            join trips t on t.trip_id = st.trip_id
            join routes r on r.route_id = t.route_id
            where st.stop_id = ? and st.pickup_type is distinct from '1'
            order by st.departure_time, st.trip_id, st.stop_sequence
        """, [stop_id]).fetchall()
        from src.common.gtfs_time import parse_gtfs_time
        deps = [Departure(tid, route, head, parse_gtfs_time(dep), sid, int(seq))
                for tid, route, head, dep, sid, seq in rows]
        return StopTimetable(stop_id=stop_id, stop_code=info[0], stop_name=info[1], departures=deps)

    def all_tram_stop_timetables(self):
        """Generator of StopTimetable for every stop with tram departures. One pass over stop_times."""
        cur = self.con.execute(f"""
            select st.stop_id, s.stop_code, s.stop_name,
                   list(struct_pack(trip_id := st.trip_id, route := r.route_short_name,
                                    headsign := coalesce(nullif(st.stop_headsign,''), t.trip_headsign, ''),
                                    dep := st.departure_time, service_id := t.service_id,
                                    seq := cast(st.stop_sequence as integer))
                        order by st.departure_time, st.trip_id, st.stop_sequence) as deps
            from stop_times st
            join trips t on t.trip_id = st.trip_id
            join routes r on r.route_id = t.route_id and r.route_type = '{TRAM_ROUTE_TYPE}'
            join stops s on s.stop_id = st.stop_id
            where st.pickup_type is distinct from '1'
            group by st.stop_id, s.stop_code, s.stop_name
        """)
        from src.common.gtfs_time import parse_gtfs_time
        while True:
            batch = cur.fetchmany(200)
            if not batch:
                break
            for stop_id, code, name, deps in batch:
                yield StopTimetable(
                    stop_id=stop_id, stop_code=code or "", stop_name=name or "",
                    departures=[Departure(d["trip_id"], d["route"], d["headsign"],
                                          parse_gtfs_time(d["dep"]), d["service_id"], d["seq"]) for d in deps],
                )

    def station_catalog(self, stops: list[StopTimetable] | None = None) -> list[dict]:
        """Group tram platforms by GTFS stop_name and attach direction aliases."""
        from collections import defaultdict
        grouped: dict[str, list[dict]] = defaultdict(list)
        source = stops if stops is not None else list(self.all_tram_stop_timetables())
        for stop in source:
            heads = sorted({d.headsign for d in stop.departures if d.headsign})
            grouped[stop.stop_name].append({
                "stop_id": stop.stop_id,
                "stop_code": stop.stop_code,
                "headsigns": heads,
            })
        catalog = [build_station(name, plats).as_dict() for name, plats in grouped.items()]
        catalog.sort(key=lambda s: s["spoken"])
        return catalog
