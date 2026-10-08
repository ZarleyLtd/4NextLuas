"""Local proof of concept: next trams at a named Luas stop.

Usage:  python tools/poc_next_tram.py Dundrum [--direction northbound] [--no-realtime] [--at HH:MM]

Reads NTA_API_KEY from .env.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv

from ingest.gtfs_static import GtfsStatic, ensure_gtfs
from src.common.gtfs_time import now_dublin
from src.common.predictions import predict, select_for_speech
from src.common.realtime import RealtimeError, fetch_trip_updates
from src.common.speech import next_trams_speech
from src.common.stations import catalog_from_dicts, find_station, match_platforms, parse_direction

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("poc")


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("station", nargs="?", default=os.getenv("POC_STATION", "Dundrum"))
    ap.add_argument("--direction", default=os.getenv("POC_DIRECTION", ""))
    ap.add_argument("--no-realtime", action="store_true")
    ap.add_argument("--at", help="pretend the time is HH:MM today (timetable only)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    args = ap.parse_args()

    now = now_dublin()
    if args.at:
        hh, mm = args.at.split(":")
        now = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        args.no_realtime = True

    t0 = time.perf_counter()
    gtfs_dir = ensure_gtfs(Path(args.cache))
    gtfs = GtfsStatic(gtfs_dir)
    log.info("GTFS feed version %s ready in %.1fs", gtfs.feed_version(), time.perf_counter() - t0)

    t1 = time.perf_counter()
    stops = list(gtfs.all_tram_stop_timetables())
    stations = catalog_from_dicts(gtfs.station_catalog(stops))
    station = find_station(stations, args.station)
    if not station:
        print(f"Station {args.station!r} not found ({len(stations)} Luas stations known).")
        return 2
    direction = parse_direction(args.direction) if args.direction else None
    platforms = match_platforms(station, direction)
    if not platforms:
        print(f"No platform match at {station.spoken} for {args.direction!r}")
        for p in station.usable_platforms():
            print(f"  {p.label}  {p.stop_id}  heads={p.headsigns}")
        return 2
    if len(platforms) > 1 and not direction:
        print(f"{station.spoken} has {len(platforms)} platforms; pass --direction")
        for p in platforms:
            print(f"  {p.label}  {p.stop_id}  heads={p.headsigns}")
        return 2
    platform = platforms[0]
    stop = next(s for s in stops if s.stop_id == platform.stop_id)
    calendar = gtfs.service_calendar(now.date() - timedelta(days=1), days=3)
    log.info("stop %s (%s): %d scheduled departures; static lookups %.1fs",
             platform.label, stop.stop_id, len(stop.departures), time.perf_counter() - t1)

    feed = None
    realtime_ok = False
    if not args.no_realtime:
        key = os.getenv("NTA_API_KEY", "").strip()
        if not key:
            print("NTA_API_KEY missing in .env; running timetable-only.")
        else:
            t2 = time.perf_counter()
            try:
                feed = fetch_trip_updates(key, timeout=15)
                realtime_ok = True
                age = int(time.time() - feed.feed_timestamp) if feed.feed_timestamp else -1
                log.info("realtime: %d trips, %.0f KB, feed age %ss, total %.2fs",
                         len(feed.trips), feed.raw_bytes / 1024, age, time.perf_counter() - t2)
            except RealtimeError as exc:
                log.error("realtime fetch failed: %s", exc)

    preds = predict(stop, calendar, feed, now)
    chosen = select_for_speech(preds, now)
    print()
    print(f"Now: {now:%a %d %b %H:%M} (Europe/Dublin)")
    for p in (preds if args.all else chosen):
        flag = "RT " if p.realtime else "sch"
        print(f"  {flag} {p.predicted:%H:%M}  {p.route:8s} {p.headsign:28s} sched {p.scheduled:%H:%M}  delay {p.delay_seconds:+d}s")
    print()
    print("Alexa would say:")
    print("  " + next_trams_speech(platform.label, chosen, now,
                                   realtime_available=realtime_ok or args.no_realtime))
    print(f"\nTotal wall time {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
