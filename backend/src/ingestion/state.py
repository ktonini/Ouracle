"""Incremental ingest detection state, fingerprints, and ingest context."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..insights.sync_freshness import ingest_advanced_data
from ..models import (
    Base,
    HeartRate,
    IngestState,
    RingBattery,
    Temperature,
)

logger = logging.getLogger("IngestState")


def naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize to naive UTC for SQLite DateTime columns and comparisons."""
    if dt is None:
        return None
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_before(left: Optional[datetime], right: Optional[datetime]) -> bool:
    """Compare datetimes safely even when one side is timezone-aware."""
    if left is None or right is None:
        return False
    return naive_utc(left) < naive_utc(right)


VOLATILE_COLUMNS = frozenset({"id"})

CONTENT_COLUMNS: Dict[str, List[str]] = {}


def _register_content_columns(model: Type[Base], exclude: Optional[frozenset] = None) -> List[str]:
    exclude = exclude or VOLATILE_COLUMNS
    cols = [c.name for c in model.__table__.columns if c.name not in exclude]
    CONTENT_COLUMNS[model.__tablename__] = cols
    return cols


def content_columns_for(model: Type[Base]) -> List[str]:
    if model.__tablename__ not in CONTENT_COLUMNS:
        _register_content_columns(model)
    return CONTENT_COLUMNS[model.__tablename__]


def content_differs(old: Base, new: Base, columns: List[str]) -> bool:
    for col in columns:
        if getattr(old, col) != getattr(new, col):
            return True
    return False


def synthetic_id(entity: str, fields: List[Any]) -> str:
    """Deterministic key from natural identifying fields (stable across exports)."""
    parts: List[str] = []
    for f in fields:
        if f is None:
            parts.append("")
        elif isinstance(f, (datetime, date)):
            parts.append(f.isoformat())
        else:
            parts.append(str(f).strip())
    digest = hashlib.sha256((entity + "|" + "\x1f".join(parts)).encode("utf-8")).hexdigest()
    return f"{entity}:{digest[:32]}"


def sha256_of_file(path: str) -> Dict[str, Any]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size": size}


def get_state(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(IngestState, key)
    if row is None or row.value is None:
        return default
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return default


def set_state(db: Session, key: str, value: Any) -> None:
    payload = json.dumps(value)
    row = db.get(IngestState, key)
    if row is None:
        db.add(
            IngestState(
                key=key,
                value=payload,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
    else:
        row.value = payload
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()


def clear_detection_state(db: Session) -> None:
    for key in ("last_zip_fingerprint", "file_fingerprints", "last_run_stats"):
        row = db.get(IngestState, key)
        if row is not None:
            db.delete(row)
    db.flush()


def compute_high_water_marks(db: Session) -> Dict[str, Optional[datetime]]:
    return {
        "heart_rate": naive_utc(db.query(func.max(HeartRate.timestamp)).scalar()),
        "temperature": naive_utc(db.query(func.max(Temperature.timestamp)).scalar()),
        "ring_battery": naive_utc(db.query(func.max(RingBattery.timestamp)).scalar()),
    }


@dataclass
class IngestCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    files_processed: int = 0
    files_skipped: int = 0


@dataclass
class IngestContext:
    db: Session
    incremental_enabled: bool
    force_full: bool
    window_days: int
    high_water_marks: Dict[str, Optional[datetime]]
    file_fingerprints: Dict[str, Any]
    new_file_fingerprints: Dict[str, Any] = field(default_factory=dict)
    counts: IngestCounts = field(default_factory=IngestCounts)
    zip_fp: Optional[Dict[str, Any]] = None
    cold_start: bool = False

    @property
    def effective_incremental(self) -> bool:
        return self.incremental_enabled and not self.force_full and not self.cold_start

    def cutoff_for(self, entity: str) -> Optional[datetime]:
        if not self.effective_incremental:
            return None
        hwm = self.high_water_marks.get(entity)
        if hwm is None:
            return None
        return naive_utc(hwm) - timedelta(days=self.window_days)

    def should_skip_file(self, filename: str, path: str) -> bool:
        """Return True when an unchanged file can be skipped (records fingerprint either way)."""
        fp = sha256_of_file(path)
        if self.effective_incremental and filename != "enhancedtag.csv":
            prev = self.file_fingerprints.get(filename)
            if prev and prev.get("sha256") == fp.get("sha256"):
                self.counts.files_skipped += 1
                return True
            self.counts.files_processed += 1
        self.new_file_fingerprints[filename] = fp
        return False


@dataclass
class IngestOutcome:
    before_latest: Optional[date]
    after_latest: Optional[date]
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    skipped_identical_zip: bool = False
    error: Optional[Exception] = None

    @property
    def advanced(self) -> bool:
        return ingest_advanced_data(self.before_latest, self.after_latest)

    @property
    def changed(self) -> bool:
        return self.inserted > 0 or self.updated > 0
