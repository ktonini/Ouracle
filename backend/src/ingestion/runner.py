"""Run ZIP ingestion off the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from ..config import config_manager
from ..database import SessionLocal
from ..insights.sync_freshness import _latest_day, apply_post_ingest_outcome
from .manager import OuraParser
from .state import (
    IngestContext,
    IngestOutcome,
    clear_detection_state,
    compute_high_water_marks,
    get_state,
    set_state,
    sha256_of_file,
)

logger = logging.getLogger("IngestRunner")


def _build_context(db: Session, force_full: bool) -> IngestContext:
    cfg = config_manager.get_config()
    incremental_enabled = bool(cfg.get("incremental_ingest_enabled", True))
    window_days = int(cfg.get("incremental_reprocess_window_days", 3))
    file_fingerprints = get_state(db, "file_fingerprints") or {}
    cold_start = not file_fingerprints
    return IngestContext(
        db=db,
        incremental_enabled=incremental_enabled,
        force_full=force_full,
        window_days=window_days,
        high_water_marks=compute_high_water_marks(db),
        file_fingerprints=file_fingerprints,
        cold_start=cold_start,
    )


def ingest_zip_blocking(
    zip_path: str,
    db: Optional[Session] = None,
    *,
    force_full: bool = False,
) -> IngestOutcome:
    """Parse a ZIP on the current thread."""

    own_session = db is None
    if own_session:
        db = SessionLocal()
    assert db is not None

    started = time.perf_counter()
    before_latest = _latest_day(db)
    ctx = _build_context(db, force_full)

    if force_full:
        clear_detection_state(db)
        ctx.file_fingerprints = {}
        ctx.cold_start = True

    zip_fp = sha256_of_file(zip_path)
    ctx.zip_fp = zip_fp

    if ctx.incremental_enabled and not force_full and not ctx.cold_start:
        last_zip = get_state(db, "last_zip_fingerprint")
        if last_zip and last_zip.get("sha256") == zip_fp.get("sha256"):
            logger.info("ZIP fingerprint unchanged — skipping parse")
            return IngestOutcome(
                before_latest=before_latest,
                after_latest=before_latest,
                skipped_identical_zip=True,
            )

    if not ctx.effective_incremental:
        config_manager.update_status(
            "Ingesting",
            message="Importing export (full ingest)…",
        )
    else:
        config_manager.update_status(
            "Ingesting",
            message="Checking what's new in this export…",
        )

    try:
        OuraParser(db, ctx).parse_zip(zip_path)
        after_latest = _latest_day(db)

        if ctx.incremental_enabled and not force_full:
            merged_fps = {**ctx.file_fingerprints, **ctx.new_file_fingerprints}
            set_state(db, "file_fingerprints", merged_fps)
            set_state(db, "last_zip_fingerprint", zip_fp)
            duration_ms = int((time.perf_counter() - started) * 1000)
            set_state(
                db,
                "last_run_stats",
                {
                    "zip_skipped": False,
                    "files_processed": ctx.counts.files_processed,
                    "files_skipped": ctx.counts.files_skipped,
                    "inserted": ctx.counts.inserted,
                    "updated": ctx.counts.updated,
                    "unchanged": ctx.counts.unchanged,
                    "duration_ms": duration_ms,
                    "advanced": after_latest is not None
                    and (before_latest is None or after_latest > before_latest),
                },
            )
        db.commit()

        return IngestOutcome(
            before_latest=before_latest,
            after_latest=after_latest,
            inserted=ctx.counts.inserted,
            updated=ctx.counts.updated,
            unchanged=ctx.counts.unchanged,
            files_processed=ctx.counts.files_processed,
            files_skipped=ctx.counts.files_skipped,
        )
    except Exception as exc:
        db.rollback()
        return IngestOutcome(
            before_latest=before_latest,
            after_latest=_latest_day(db),
            error=exc,
        )
    finally:
        if own_session:
            db.close()


async def ingest_zip_async(
    zip_path: str,
    *,
    update_status: bool = True,
    success_message: str = "Sync and ingestion complete!",
    force_full: bool = False,
) -> bool:
    """Ingest in a worker thread and optionally update automation status.

    Returns True when the newest local Oura day moved forward.
    """

    outcome = await asyncio.to_thread(
        ingest_zip_blocking, zip_path, force_full=force_full
    )
    if update_status:
        apply_post_ingest_outcome(
            outcome,
            partial_error=outcome.error,
            success_message=success_message,
        )
    if outcome.error:
        raise outcome.error
    return outcome.advanced
