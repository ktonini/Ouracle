"""Assemble a night's timeline from decoded ring events.

The ring stamps events with its own clock in deciseconds since power-on, so
everything here hinges on `time_sync` events (tag 0x42), which carry a unix
timestamp alongside that clock and let us convert one to the other.

Produces per-minute series for heart rate, movement and temperature, plus the
ring's own detected bedtime window — all from data read over Bluetooth, with
no dependency on Oura having scored the night.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import RingEventRaw

logger = logging.getLogger("RingNight")

# Event tags contributing to a night view.
TAG_TIME_SYNC = 0x42
TAG_TEMP_SLEEP = 0x75
TAG_IBI = 0x60
TAG_GREEN_IBI = 0x80
TAG_SLEEP_ACM = 0x72
TAG_BEDTIME = 0x76

PLAUSIBLE_IBI_MS = range(300, 2001)


def ring_clock_offset(db: Session) -> Optional[float]:
    """Seconds to add to (ring deciseconds / 10) to get unix time.

    Uses the median across all time_sync events; they agree to a few seconds,
    and the median ignores any outlier from a clock reset.
    """
    rows = (
        db.query(RingEventRaw)
        .filter(RingEventRaw.tag == TAG_TIME_SYNC, RingEventRaw.decoded.isnot(None))
        .all()
    )
    offsets = [
        row.decoded["unix_time"] - row.timestamp / 10.0
        for row in rows
        if row.decoded.get("unix_time")
    ]
    return median(offsets) if offsets else None


def to_unix(ds: int, offset: float) -> float:
    return offset + ds / 10.0


def to_ring_ds(when: datetime, offset: float) -> int:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return int((when.timestamp() - offset) * 10)


def _bucket_minutes(
    samples: List[Tuple[float, float]], minutes: int = 5, stat: str = "mean"
) -> List[Dict[str, Any]]:
    """Aggregate samples into fixed buckets: [(unix_seconds, value), …].

    `stat` selects mean or max — movement peaks matter for wake detection,
    where an average washes out a brief but decisive burst.
    """
    if not samples:
        return []
    width = minutes * 60
    buckets: Dict[int, List[float]] = {}
    for when, value in samples:
        buckets.setdefault(int(when // width) * width, []).append(value)

    def reduce(values: List[float]) -> float:
        return max(values) if stat == "max" else sum(values) / len(values)

    return [
        {
            "t": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "value": round(reduce(values), 3),
        }
        for start, values in sorted(buckets.items())
    ]


def _variability_per_bucket(
    samples: List[Tuple[float, int]], minutes: int
) -> Dict[str, float]:
    """RMSSD-style variability per bucket, keyed by the bucket's timestamp."""
    width = minutes * 60
    buckets: Dict[int, List[int]] = {}
    for when, interval in samples:
        buckets.setdefault(int(when // width) * width, []).append(interval)

    out: Dict[str, float] = {}
    for start, intervals in buckets.items():
        diffs = [
            b - a
            for a, b in zip(intervals, intervals[1:])
            if abs(b - a) < 300  # ignore missed/spurious beats
        ]
        if not diffs:
            continue
        key = datetime.fromtimestamp(start, timezone.utc).isoformat()
        out[key] = round((sum(d * d for d in diffs) / len(diffs)) ** 0.5, 1)
    return out


def build_night(
    db: Session, start: datetime, end: datetime, bucket_minutes: int = 5
) -> Dict[str, Any]:
    """Series for a wall-clock window, from ring events alone."""
    offset = ring_clock_offset(db)
    if offset is None:
        return {"error": "no time_sync events; ring clock cannot be aligned"}

    lo, hi = to_ring_ds(start, offset), to_ring_ds(end, offset)
    rows = (
        db.query(RingEventRaw)
        .filter(
            RingEventRaw.timestamp >= lo,
            RingEventRaw.timestamp <= hi,
            RingEventRaw.decoded.isnot(None),
        )
        .order_by(RingEventRaw.timestamp)
        .all()
    )

    hr: List[Tuple[float, float]] = []
    movement: List[Tuple[float, float]] = []
    temperature: List[Tuple[float, float]] = []
    beats: List[int] = []
    ibi_samples: List[Tuple[float, int]] = []

    for row in rows:
        when = to_unix(row.timestamp, offset)
        decoded = row.decoded or {}

        if row.tag in (TAG_IBI, TAG_GREEN_IBI):
            good = [i for i in decoded.get("ibi_ms", []) if i in PLAUSIBLE_IBI_MS]
            beats.extend(good)
            # Spread the packet's beats across the interval they span.
            elapsed = 0.0
            for interval in good:
                moment = when + elapsed / 1000.0
                hr.append((moment, 60_000 / interval))
                ibi_samples.append((moment, interval))
                elapsed += interval

        elif row.tag == TAG_SLEEP_ACM:
            values = decoded.get("acm_mad") or []
            if values:
                # Six sub-samples spanning the period: keep them separately so
                # buckets can see peaks, not just the period's average.
                span = 60.0
                for offset, value in enumerate(values):
                    movement.append((when + offset * span / len(values), value))

        elif row.tag == TAG_TEMP_SLEEP:
            temps = decoded.get("temps_c") or []
            if temps:
                temperature.append((when, sum(temps) / len(temps)))

    hr_series = _bucket_minutes(hr, bucket_minutes)
    # Beat-to-beat variability per bucket, which staging uses to separate REM
    # (variable) from deep sleep (steady).
    variability = _variability_per_bucket(ibi_samples, bucket_minutes)
    # Lowest heart rate comes from the bucketed series, not a single beat: one
    # long interval at the edge of the plausible range would otherwise report
    # an impossible resting rate (a stray 2000 ms beat reads as 30 bpm).
    lowest = round(min(point["value"] for point in hr_series)) if hr_series else None

    return {
        "start": start.replace(tzinfo=timezone.utc).isoformat(),
        "end": end.replace(tzinfo=timezone.utc).isoformat(),
        "heart_rate": hr_series,
        "movement": _bucket_minutes(movement, bucket_minutes),
        "movement_peak": _bucket_minutes(movement, bucket_minutes, stat="max"),
        "temperature": _bucket_minutes(temperature, bucket_minutes),
        "beats": len(beats),
        "lowest_hr": lowest,
        "average_hr": round(60_000 / (sum(beats) / len(beats))) if beats else None,
        "event_count": len(rows),
        "hrv": variability,
    }


def detected_bedtimes(db: Session) -> List[Dict[str, Any]]:
    """Sleep windows the ring detected on its own (tag 0x76)."""
    offset = ring_clock_offset(db)
    if offset is None:
        return []
    rows = (
        db.query(RingEventRaw)
        .filter(RingEventRaw.tag == TAG_BEDTIME, RingEventRaw.decoded.isnot(None))
        .order_by(RingEventRaw.timestamp)
        .all()
    )
    windows = []
    for row in rows:
        decoded = row.decoded
        start = decoded.get("bedtime_start_ds")
        end = decoded.get("bedtime_end_ds")
        if not start or not end:
            continue
        windows.append(
            {
                "start": datetime.fromtimestamp(
                    to_unix(start, offset), timezone.utc
                ).isoformat(),
                "end": datetime.fromtimestamp(
                    to_unix(end, offset), timezone.utc
                ).isoformat(),
                "duration_hours": decoded.get("duration_hours"),
            }
        )
    return windows


def coverage(db: Session) -> Optional[Dict[str, Any]]:
    """Wall-clock span of the events we hold, so callers can show what's real."""
    offset = ring_clock_offset(db)
    if offset is None:
        return None
    first = db.query(RingEventRaw).order_by(RingEventRaw.timestamp).first()
    last = db.query(RingEventRaw).order_by(RingEventRaw.timestamp.desc()).first()
    if not first or not last:
        return None
    return {
        "from": datetime.fromtimestamp(
            to_unix(first.timestamp, offset), timezone.utc
        ).isoformat(),
        "to": datetime.fromtimestamp(
            to_unix(last.timestamp, offset), timezone.utc
        ).isoformat(),
    }
