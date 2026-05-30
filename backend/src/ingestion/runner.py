"""Run ZIP ingestion off the asyncio event loop.

Oura export parsing is CPU/IO heavy and synchronous. Running it on the main
event loop blocks every API request (including /check-status) until ingest
finishes, which makes sync appear broken.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..insights.sync_freshness import _latest_day, apply_post_ingest_result, ingest_advanced_data
from .manager import OuraParser


def ingest_zip_blocking(
    zip_path: str,
    db: Optional[Session] = None,
) -> Tuple[Optional[date], Optional[date], Optional[Exception]]:
    """Parse a ZIP on the current thread. Returns (before_latest, after_latest, error)."""

    own_session = db is None
    if own_session:
        db = SessionLocal()
    assert db is not None
    before_latest = _latest_day(db)
    try:
        OuraParser(db).parse_zip(zip_path)
        after_latest = _latest_day(db)
        db.commit()
        return before_latest, after_latest, None
    except Exception as exc:
        db.rollback()
        return before_latest, _latest_day(db), exc
    finally:
        if own_session:
            db.close()


async def ingest_zip_async(
    zip_path: str,
    *,
    update_status: bool = True,
    success_message: str = "Sync and ingestion complete!",
) -> bool:
    """Ingest in a worker thread and optionally update automation status.

    Returns True when the newest local Oura day moved forward.
    """

    before_latest, after_latest, error = await asyncio.to_thread(
        ingest_zip_blocking, zip_path
    )
    advanced = ingest_advanced_data(before_latest, after_latest)
    if update_status:
        apply_post_ingest_result(
            before_latest,
            after_latest,
            partial_error=error,
            success_message=success_message,
        )
    if error:
        raise error
    return advanced
