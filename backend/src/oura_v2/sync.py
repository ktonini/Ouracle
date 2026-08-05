"""Incremental sync from the Oura API v2 into the shared database.

Per-collection watermarks live in the existing ``ingest_state`` key/value table
under ``oura_v2:<collection>``. Each run re-fetches a small overlap window so
late-arriving revisions (Oura rescoring recent days) are picked up.

Run as a CLI:

    python -m backend.src.oura_v2.sync --backfill-days 3650
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import (
    Activity,
    CardiovascularAge,
    HeartRate,
    IngestState,
    Meditation,
    Readiness,
    Resilience,
    RingBattery,
    RingConfiguration,
    Sleep,
    SleepSession,
    Tag,
    Workout,
)
from . import mappers
from .client import OuraV2Client
from .credentials import CredentialError, provider_from_env

logger = logging.getLogger("OuraV2Sync")

WATERMARK_PREFIX = "oura_v2:"
DEFAULT_BACKFILL_DAYS = 3650
DEFAULT_OVERLAP_DAYS = 3
# The datetime-windowed endpoints reject spans longer than 30 days; stay under.
MAX_DATETIME_WINDOW_DAYS = 28


# --- Watermarks --------------------------------------------------------------

def get_watermark(db: Session, collection: str) -> Optional[date]:
    row = db.get(IngestState, WATERMARK_PREFIX + collection)
    return date.fromisoformat(row.value) if row and row.value else None


def set_watermark(db: Session, collection: str, day: date) -> None:
    key = WATERMARK_PREFIX + collection
    row = db.get(IngestState, key)
    if row is None:
        row = IngestState(key=key)
        db.add(row)
    row.value = day.isoformat()
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


# --- Upsert strategies -------------------------------------------------------

def upsert_by_day(db: Session, model, values: Dict[str, Any]) -> None:
    """Day-unique tables (sleep, activity, readiness, ...).

    Updates the existing row for the day (keeping its primary key) or inserts.
    Merge mappers return only a subset of columns; ``None`` values never
    overwrite data another collection already filled in.
    """
    day = values.get("day")
    if day is None:
        return
    existing = db.query(model).filter(model.day == day).one_or_none()
    if existing is None:
        if "id" not in values:
            # A merge fragment for a day we have no base row for yet: synthesize
            # a stable id so the fragment isn't dropped.
            values = {"id": f"{model.__tablename__}-{day.isoformat()}", **values}
        db.add(model(**values))
        # Sessions run with autoflush=False; flush so a second document for
        # the same day within this batch sees the row and updates it instead
        # of violating the day-unique constraint at commit.
        db.flush()
        return
    for column, value in values.items():
        if column in ("id", "day") or value is None:
            continue
        setattr(existing, column, value)


def upsert_by_pk(db: Session, model, values: Dict[str, Any]) -> None:
    """Id- or timestamp-keyed tables: plain merge on the primary key."""
    pk = model.__mapper__.primary_key[0].name
    if values.get(pk) is None:
        return
    db.merge(model(**values))


# --- Collection registry -----------------------------------------------------

class CollectionSpec:
    def __init__(
        self,
        name: str,
        model,
        mapper: Callable[[Dict[str, Any]], Dict[str, Any]],
        upsert: Callable[[Session, Any, Dict[str, Any]], None],
        datetime_params: bool = False,
        windowless: bool = False,
    ):
        self.name = name
        self.model = model
        self.mapper = mapper
        self.upsert = upsert
        self.datetime_params = datetime_params
        self.windowless = windowless


COLLECTIONS: List[CollectionSpec] = [
    CollectionSpec("daily_sleep", Sleep, mappers.map_daily_sleep, upsert_by_day),
    CollectionSpec("daily_spo2", Sleep, mappers.merge_daily_spo2, upsert_by_day),
    CollectionSpec("sleep_time", Sleep, mappers.merge_sleep_time, upsert_by_day),
    CollectionSpec("daily_activity", Activity, mappers.map_daily_activity, upsert_by_day),
    CollectionSpec("daily_readiness", Readiness, mappers.map_daily_readiness, upsert_by_day),
    CollectionSpec("daily_stress", Readiness, mappers.merge_daily_stress, upsert_by_day),
    CollectionSpec("daily_resilience", Resilience, mappers.map_daily_resilience, upsert_by_day),
    CollectionSpec(
        "daily_cardiovascular_age",
        CardiovascularAge,
        mappers.map_daily_cardiovascular_age,
        upsert_by_day,
    ),
    CollectionSpec("sleep", SleepSession, mappers.map_sleep_session, upsert_by_pk),
    CollectionSpec("workout", Workout, mappers.map_workout, upsert_by_pk),
    CollectionSpec("session", Meditation, mappers.map_session, upsert_by_pk),
    CollectionSpec("enhanced_tag", Tag, mappers.map_enhanced_tag, upsert_by_pk),
    CollectionSpec(
        "ring_configuration",
        RingConfiguration,
        mappers.map_ring_configuration,
        upsert_by_pk,
        windowless=True,
    ),
    CollectionSpec(
        "heartrate", HeartRate, mappers.map_heartrate_row, upsert_by_pk, datetime_params=True
    ),
    CollectionSpec(
        "ring_battery_level",
        RingBattery,
        mappers.map_ring_battery_row,
        upsert_by_pk,
        datetime_params=True,
    ),
]


# --- Sync driver -------------------------------------------------------------

def sync_collection(
    db: Session,
    client: OuraV2Client,
    spec: CollectionSpec,
    backfill_days: int,
    overlap_days: int,
    today: Optional[date] = None,
) -> int:
    today = today or datetime.now(timezone.utc).date()

    if spec.windowless:
        start: Optional[date] = None
        end: Optional[date] = None
    else:
        watermark = get_watermark(db, spec.name)
        if watermark is None:
            start = today - timedelta(days=backfill_days)
        else:
            start = watermark - timedelta(days=overlap_days)
        # end_date is inclusive; add a day so today's partial data lands too.
        end = today + timedelta(days=1)

    windows: List[tuple]
    if spec.datetime_params and start is not None and end is not None:
        # The heartrate/ring_battery_level endpoints reject ranges over 30
        # days; walk the span in chunks.
        windows = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=MAX_DATETIME_WINDOW_DAYS), end)
            windows.append(
                (
                    datetime.combine(chunk_start, dtime.min, tzinfo=timezone.utc),
                    datetime.combine(chunk_end, dtime.min, tzinfo=timezone.utc),
                )
            )
            chunk_start = chunk_end
    else:
        windows = [(start, end)]

    count = 0
    for fetch_start, fetch_end in windows:
        for doc in client.fetch_collection(
            spec.name, fetch_start, fetch_end, datetime_params=spec.datetime_params
        ):
            spec.upsert(db, spec.model, spec.mapper(doc))
            count += 1

    if not spec.windowless:
        set_watermark(db, spec.name, today)
    db.commit()
    logger.info("%s: %d documents", spec.name, count)
    return count


def run_sync(
    db: Session,
    client: OuraV2Client,
    backfill_days: int = DEFAULT_BACKFILL_DAYS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    only: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Sync every collection; returns per-collection document counts.

    A failure in one collection aborts the run (consistent watermarks beat
    partial progress), except that 403s — scopes/tiers not exposing a
    collection — skip just that collection.
    """
    counts: Dict[str, int] = {}
    for spec in COLLECTIONS:
        if only and spec.name not in only:
            continue
        try:
            counts[spec.name] = sync_collection(
                db, client, spec, backfill_days, overlap_days
            )
        except CredentialError as e:
            if "403" in str(e):
                logger.warning("Skipping %s: %s", spec.name, e)
                db.rollback()
                counts[spec.name] = -1
                continue
            raise
    return counts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Oura API v2 data into Ouracle.")
    parser.add_argument("--backfill-days", type=int, default=DEFAULT_BACKFILL_DAYS)
    parser.add_argument("--overlap-days", type=int, default=DEFAULT_OVERLAP_DAYS)
    parser.add_argument(
        "--collections",
        nargs="*",
        help="Subset of collections to sync (default: all).",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Oura's sandbox endpoints (fake data, any token accepted).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    # Imported lazily: database.py touches the data dir at import time.
    from ..database import SessionLocal, init_db

    try:
        if args.sandbox:
            from .credentials import StaticTokenProvider

            credentials = StaticTokenProvider("sandbox")
        else:
            credentials = provider_from_env()
        client = OuraV2Client(credentials, sandbox=args.sandbox)

        init_db()
        db = SessionLocal()
        try:
            counts = run_sync(
                db,
                client,
                backfill_days=args.backfill_days,
                overlap_days=args.overlap_days,
                only=args.collections,
            )
        finally:
            db.close()
    except CredentialError as e:
        logger.critical("Credential failure: %s", e)
        return 2

    total = sum(c for c in counts.values() if c > 0)
    skipped = [name for name, c in counts.items() if c < 0]
    logger.info("Sync complete: %d documents across %d collections", total, len(counts))
    if skipped:
        logger.warning("Collections skipped (403): %s", ", ".join(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
