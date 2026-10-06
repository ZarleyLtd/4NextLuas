"""Daily timetable build: TFI GTFS zip -> per-stop items in DynamoDB.

Run locally:   python -m ingest.build_timetable [--dry-run] [--force] [--limit N]
Run in CI:     see .github/workflows/ingest.yml

Only stops whose departures changed since the last run are written (hash manifest),
and writes are paced to stay under the table's 25 WCU/s free-tier allowance.
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
from src.common.store import Store, content_hash, pack

log = logging.getLogger("ingest")

WCU_BUDGET_PER_SECOND = 18.0      # leave headroom under the 25 WCU provisioned
CALENDAR_DAYS = 16


class WritePacer:
    """Token bucket: 1 WCU per KB written (rounded up), refilled at WCU_BUDGET_PER_SECOND."""

    def __init__(self, rate: float = WCU_BUDGET_PER_SECOND, burst: float = 100.0):
        self.rate, self.capacity = rate, burst
        self.tokens = burst
        self.last = time.monotonic()

    def consume(self, size_bytes: int) -> None:
        need = max(1, -(-size_bytes // 1024))
        while True:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= need:
                self.tokens -= need
                return
            time.sleep((need - self.tokens) / self.rate)


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build everything, write nothing, print size stats")
    ap.add_argument("--force", action="store_true", help="ignore the manifest and rewrite every stop")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N stops (testing)")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    table = os.environ.get("FOURNEXTLUAS_TABLE", "FourNextLuas")
    region = os.environ.get("AWS_REGION", "eu-west-1")

    t0 = time.perf_counter()
    gtfs = GtfsStatic(ensure_gtfs(Path(args.cache)))
    feed_version = gtfs.feed_version()
    log.info("GTFS feed version %s", feed_version)

    store = None if args.dry_run else Store(table, region)
    old_manifest: dict[str, str] = {}
    old_version = None
    if store:
        old_manifest, old_version = store.get_manifest()
        log.info("manifest: %d stops, feed version %s", len(old_manifest), old_version)
        if old_version and old_version != feed_version:
            log.info("new GTFS publish (%s -> %s); many stop rewrites expected", old_version, feed_version)
    if args.force:
        old_manifest = {}

    pacer = WritePacer()
    new_manifest: dict[str, str] = {}
    stats = {"stops": 0, "written": 0, "unchanged": 0, "bytes": 0, "max_bytes": 0, "max_stop": ""}
    sizes: list[int] = []

    collected = []
    for stop in gtfs.all_tram_stop_timetables():
        stats["stops"] += 1
        if args.limit and stats["stops"] > args.limit:
            break
        collected.append(stop)
        rows = [d.to_row() for d in stop.departures]
        h = content_hash([stop.stop_code, stop.stop_name, rows])
        new_manifest[stop.stop_id] = h
        if old_manifest.get(stop.stop_id) == h:
            stats["unchanged"] += 1
            continue
        if store:
            size = store.put_stop(stop, feed_version, h)
            pacer.consume(size)
        else:
            size = len(pack(rows)) + 200
        sizes.append(size)
        stats["written"] += 1
        stats["bytes"] += size
        if size > stats["max_bytes"]:
            stats["max_bytes"], stats["max_stop"] = size, f"{stop.stop_id} {stop.stop_name} ({len(rows)} deps)"
        if stats["written"] % 500 == 0:
            log.info("... %d stops, %d written, %.1f MB, %.0fs", stats["stops"], stats["written"],
                     stats["bytes"] / 1e6, time.perf_counter() - t0)

    # Remove stops that disappeared from the feed.
    removed = [sid for sid in old_manifest if sid not in new_manifest] if not args.limit else []
    if store:
        for sid in removed:
            store.delete_stop(sid)
            pacer.consume(1024)

    stations = gtfs.station_catalog(collected)
    calendar = gtfs.service_calendar(now_dublin().date() - timedelta(days=1), days=CALENDAR_DAYS)
    if store:
        store.put_stations(stations)
        store.put_calendar(calendar)
        store.put_manifest(new_manifest, feed_version)
    else:
        log.info("stations item %.1f KB, calendar item %.1f KB, manifest item %.1f KB",
                 len(pack(stations)) / 1024,
                 len(pack({k: sorted(v) for k, v in calendar.items()})) / 1024,
                 len(pack(new_manifest)) / 1024)

    if sizes:
        sizes.sort()
        pct = lambda p: sizes[min(len(sizes) - 1, int(p * len(sizes)))]
        log.info("item size bytes: p50 %d, p90 %d, p99 %d, max %d (%s)",
                 pct(0.5), pct(0.9), pct(0.99), stats["max_bytes"], stats["max_stop"])
    log.info("done: %d stops, %d written, %d unchanged, %d removed, %.1f MB, %d stations, %.0fs%s",
             stats["stops"], stats["written"], stats["unchanged"], len(removed), stats["bytes"] / 1e6,
             len(stations), time.perf_counter() - t0, " (dry run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
