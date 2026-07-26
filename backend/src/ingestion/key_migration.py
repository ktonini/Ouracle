"""One-time migration to deterministic entity keys (spec §5.5 / design §9.3)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import (
    Activity,
    CardiovascularAge,
    Meditation,
    Readiness,
    Resilience,
    RingConfiguration,
    Sleep,
    SleepSession,
    Tag,
    Workout,
)
from .state import get_state, set_state, synthetic_id

logger = logging.getLogger("KeyMigration")

SESSION_SPECS = [
    (SleepSession, "sleep_session", lambda r: [r.day, r.bedtime_start, r.type]),
    (Workout, "workout", lambda r: [r.day, r.start_time, r.activity or r.intensity]),
    (Meditation, "meditation", lambda r: [r.day, r.start_time, r.type]),
    (Tag, "tag", lambda r: [r.start_time, r.tag_type_code, r.comment]),
    (
        RingConfiguration,
        "ring_configuration",
        lambda r: [r.firmware_version, r.hardware_type, r.color, r.size],
    ),
]

DAY_SPECS = [
    (Sleep, "sleep"),
    (Activity, "activity"),
    (Readiness, "readiness"),
    (Resilience, "resilience"),
    (CardiovascularAge, "cardiovascular_age"),
]


def normalize_keys_if_needed(db: Session) -> None:
    if get_state(db, "schema_normalized_version") == {"version": 1}:
        return

    logger.info("Running one-time deterministic key normalization…")
    for model, table in DAY_SPECS:
        for row in db.query(model).all():
            row.id = synthetic_id(table, [row.day])

    for model, table, fields_fn in SESSION_SPECS:
        seen: dict = {}
        for row in db.query(model).order_by(model.id).all():
            new_id = synthetic_id(table, fields_fn(row))
            if new_id in seen:
                db.delete(row)
            else:
                seen[new_id] = row
                row.id = new_id

    set_state(db, "schema_normalized_version", {"version": 1})
    db.commit()
    logger.info("Key normalization complete.")
