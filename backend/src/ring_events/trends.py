"""Per-night summaries from the ring, beside Oura's own figures.

One night at a time hides the thing sleep data is actually good for: whether
something is drifting. This assembles the series — our staging, breathing
rate, saturation and desaturation index — alongside the numbers Oura produced
for the same nights.

Keeping both on the same axes is also a standing check. Our SpO2 rests on a
calibration that is refitted nightly, and our staging on a model that is
retrained nightly; if either starts disagreeing with the cloud, the divergence
shows up here rather than waiting for someone to run a script.
"""

from __future__ import annotations

import logging
import json
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import IngestState, RingEventRaw, Sleep, SleepSession
from ..paths import get_user_data_dir
from .night import build_night
from .spo2 import desaturations, estimate, ratios_between, series
from .staging import build_epochs, stage_epochs, summarise

logger = logging.getLogger("RingTrends")

# Each night costs a scan of its events plus staging, so this is bounded.
MAX_NIGHTS = 90
CACHE_PREFIX = "ring_trends:"


def _primary_sessions(db: Session, days: int) -> List[SleepSession]:
    """The longest scored session for each of the last `days` days."""
    cutoff = date.today() - timedelta(days=days)
    best: Dict[date, SleepSession] = {}
    for session in (
        db.query(SleepSession)
        .filter(SleepSession.day >= cutoff)
        .order_by(SleepSession.day)
        .all()
    ):
        if not session.bedtime_start or not session.bedtime_end:
            continue
        current = best.get(session.day)
        if current is None or (session.total_sleep_duration or 0) > (
            current.total_sleep_duration or 0
        ):
            best[session.day] = session
    return [best[day] for day in sorted(best)]


def _ours(db: Session, session: SleepSession) -> Dict[str, Any]:
    """What the ring alone says about a night."""
    night = build_night(db, session.bedtime_start, session.bedtime_end)
    if night.get("error") or not night.get("heart_rate"):
        return {}

    staged = stage_epochs(
        build_epochs(
            night.get("heart_rate", []),
            night.get("movement", []),
            night.get("hrv", {}),
            movement_peak=night.get("movement_peak", []),
            temperature=night.get("temperature", []),
            ibi_features=night.get("ibi_features", {}),
        )
    )
    summary = summarise(staged) if staged else {}

    rates = [
        f["breath_rate"]
        for f in (night.get("ibi_features") or {}).values()
        if f.get("breath_rate") is not None
    ]
    dips = desaturations(
        series(db, session.bedtime_start, session.bedtime_end, minutes=1), minutes=1
    )

    return {
        "deep_minutes": summary.get("deep_minutes"),
        "light_minutes": summary.get("light_minutes"),
        "rem_minutes": summary.get("rem_minutes"),
        "awake_minutes": summary.get("awake_minutes"),
        "asleep_minutes": summary.get("asleep_minutes"),
        "breath_rate": round(median(rates), 1) if len(rates) >= 5 else None,
        "spo2_percent": estimate(
            ratios_between(db, session.bedtime_start, session.bedtime_end)
        ),
        "desaturation_index": dips["index"],
        "lowest_spo2": dips["lowest"],
        "average_hr": night.get("average_hr"),
        "lowest_hr": night.get("lowest_hr"),
        "method": summary.get("method"),
    }


def _theirs(db: Session, session: SleepSession) -> Dict[str, Any]:
    """The same night as Oura scored it."""
    daily = db.query(Sleep).filter(Sleep.day == session.day).one_or_none()
    return {
        "deep_minutes": (session.deep_sleep_duration or 0) // 60 or None,
        "light_minutes": (session.light_sleep_duration or 0) // 60 or None,
        "rem_minutes": (session.rem_sleep_duration or 0) // 60 or None,
        "awake_minutes": (session.awake_time or 0) // 60 or None,
        "asleep_minutes": (session.total_sleep_duration or 0) // 60 or None,
        "breath_rate": getattr(session, "average_breath", None),
        "spo2_percent": getattr(daily, "average_spo2", None) if daily else None,
        "average_hr": session.average_heart_rate,
        "lowest_hr": session.lowest_heart_rate,
        "hrv": session.average_hrv,
        "score": getattr(daily, "score", None) if daily else None,
    }


def _fingerprint(db: Session, session: SleepSession) -> str:
    """What a night's summary depends on.

    The events themselves, and the two things refitted nightly. Any of them
    moving means the cached answer is stale; none of them moving means a past
    night cannot have changed.
    """
    from .night import ring_clock_offset, to_ring_ds

    offset = ring_clock_offset(db)
    count = 0
    if offset is not None:
        count = (
            db.query(RingEventRaw)
            .filter(
                RingEventRaw.timestamp >= to_ring_ds(session.bedtime_start, offset),
                RingEventRaw.timestamp <= to_ring_ds(session.bedtime_end, offset),
            )
            .count()
        )

    stamps = []
    for name in ("sleep_model.json", "spo2_calibration.json"):
        path = get_user_data_dir() / name
        try:
            stamps.append(str(int(path.stat().st_mtime)))
        except OSError:
            stamps.append("-")
    return f"{count}:{':'.join(stamps)}"


def nightly_summaries(
    db: Session, days: int = 30, use_cache: bool = True
) -> List[Dict[str, Any]]:
    """Both views of every scored night in the window, oldest first.

    Each night costs several passes over its events, so a long window was slow
    enough to be unusable — 90 days took the better part of a minute. Past
    nights are cached against a fingerprint of what they depend on.
    """
    days = max(1, min(days, MAX_NIGHTS))
    out: List[Dict[str, Any]] = []
    dirty = False

    for session in _primary_sessions(db, days):
        key = CACHE_PREFIX + str(session.day)
        fingerprint = _fingerprint(db, session) if use_cache else ""
        row: Optional[Dict[str, Any]] = None

        if use_cache:
            cached = db.get(IngestState, key)
            if cached and cached.value:
                try:
                    blob = json.loads(cached.value)
                    if blob.get("fingerprint") == fingerprint:
                        row = blob["row"]
                except (ValueError, KeyError):
                    row = None

        if row is None:
            row = {
                "day": str(session.day),
                "ours": _ours(db, session),
                "theirs": _theirs(db, session),
            }
            if use_cache:
                state = db.get(IngestState, key)
                if state is None:
                    state = IngestState(key=key)
                    db.add(state)
                state.value = json.dumps({"fingerprint": fingerprint, "row": row})
                state.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                dirty = True
        out.append(row)

    if dirty:
        db.commit()
    return out


def agreement(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean absolute difference per metric, for the nights that have both.

    A number that grows is the signal worth acting on — either the ring stopped
    reporting something, or a refit went somewhere the cloud did not.
    """
    metrics = ("breath_rate", "spo2_percent", "deep_minutes", "rem_minutes", "lowest_hr")
    out: Dict[str, Any] = {}
    for metric in metrics:
        pairs = [
            (row["ours"].get(metric), row["theirs"].get(metric))
            for row in rows
            if row["ours"].get(metric) is not None
            and row["theirs"].get(metric) is not None
        ]
        if not pairs:
            continue
        out[metric] = {
            "nights": len(pairs),
            "mean_abs_difference": round(
                sum(abs(a - b) for a, b in pairs) / len(pairs), 2
            ),
            "bias": round(sum(a - b for a, b in pairs) / len(pairs), 2),
        }
    return out
