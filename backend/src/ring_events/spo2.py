"""Blood oxygen saturation from the ring's ratio-of-ratios.

A pulse oximeter measures R — how much more red light is absorbed than
infrared — and turns it into a saturation through an empirical calibration,
`SpO2 = A - B*R`. The ring reports R (tag 0x8b) rather than the finished
number, so the calibration has to come from somewhere.

It is fitted here from the user's own nights, against Oura's `average_spo2`.
That keeps it honest for this ring rather than baking in a constant measured
on someone else's, and it improves as nights accumulate — the same shape as
the staging model.

    python -m backend.src.ring_events.spo2
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import RingEventRaw, Sleep, SleepSession
from ..paths import get_user_data_dir
from .night import ring_clock_offset, to_ring_ds, to_unix

logger = logging.getLogger("RingSpO2")

TAG_SPO2_R = 0x8B
CALIBRATION_FILE = "spo2_calibration.json"

# The textbook curve, used until enough nights exist to fit a better one.
# Approximate by construction: it is the population calibration, not this
# ring's, and the fit typically lands some way from it.
DEFAULT_A = 110.0
DEFAULT_B = 0.34

# Below this a night's R is too sparse to average meaningfully.
MIN_RATIOS_PER_NIGHT = 200
# Per bucket the bar is much lower — the ring records around ten readings a
# minute — but a bucket built from two readings is noise.
MIN_RATIOS_PER_BUCKET = 8

# A drop of this much below the recent baseline is a desaturation, the
# threshold sleep medicine uses for the oxygen desaturation index.
DESATURATION_DROP = 3.0
# The baseline is the median of the preceding stretch rather than the whole
# night: saturation drifts, and a dip is a departure from where you just were.
BASELINE_MINUTES = 10
# An event ends when saturation comes back to within this of the baseline, so
# one long dip counts once instead of flickering across the threshold.
RECOVERY_MARGIN = 1.0
# Two coefficients fitted on fewer nights than this is not worth trusting.
MIN_NIGHTS_TO_FIT = 4


def ratios_between(db: Session, start: datetime, end: datetime) -> List[int]:
    """Every R reading the ring recorded in a window."""
    offset = ring_clock_offset(db)
    if offset is None:
        return []
    lo, hi = to_ring_ds(start, offset), to_ring_ds(end, offset)
    values: List[int] = []
    for row in (
        db.query(RingEventRaw)
        .filter(
            RingEventRaw.tag == TAG_SPO2_R,
            RingEventRaw.timestamp >= lo,
            RingEventRaw.timestamp <= hi,
            RingEventRaw.decoded.isnot(None),
        )
        .all()
    ):
        values.extend((row.decoded or {}).get("ratio", []))
    return values


def ratio_samples(db: Session, start: datetime, end: datetime) -> List[Tuple[float, int]]:
    """(unix seconds, R) for a window, so readings can be placed in time."""
    offset = ring_clock_offset(db)
    if offset is None:
        return []
    lo, hi = to_ring_ds(start, offset), to_ring_ds(end, offset)
    out: List[Tuple[float, int]] = []
    for row in (
        db.query(RingEventRaw)
        .filter(
            RingEventRaw.tag == TAG_SPO2_R,
            RingEventRaw.timestamp >= lo,
            RingEventRaw.timestamp <= hi,
            RingEventRaw.decoded.isnot(None),
        )
        .order_by(RingEventRaw.timestamp)
        .all()
    ):
        ratios = (row.decoded or {}).get("ratio", [])
        when = to_unix(row.timestamp, offset)
        # A frame's readings are consecutive samples; spread them across the
        # second rather than stacking them all on one instant.
        for index, ratio in enumerate(ratios):
            out.append((when + index, ratio))
    return out


def _saturation(ratios: List[int], calibration: Dict[str, Any]) -> Optional[float]:
    if not ratios:
        return None
    value = calibration["a"] - calibration["b"] * mean(ratios)
    return value if 70.0 <= value <= 100.0 else None


def series(
    db: Session, start: datetime, end: datetime, minutes: int = 5
) -> List[Dict[str, Any]]:
    """Saturation through the night, one point per `minutes`."""
    samples = ratio_samples(db, start, end)
    if not samples:
        return []
    calibration = load_calibration()
    width = minutes * 60
    buckets: Dict[int, List[int]] = {}
    for when, ratio in samples:
        buckets.setdefault(int(when // width) * width, []).append(ratio)

    points = []
    for bucket_start, ratios in sorted(buckets.items()):
        if len(ratios) < MIN_RATIOS_PER_BUCKET:
            continue
        value = _saturation(ratios, calibration)
        if value is None:
            continue
        points.append(
            {
                "t": datetime.fromtimestamp(bucket_start, timezone.utc).isoformat(),
                "value": round(value, 1),
            }
        )
    return points


def desaturations(points: List[Dict[str, Any]], minutes: int = 1) -> Dict[str, Any]:
    """Drops of 3% or more below the recent baseline, and the rate per hour.

    This is the oxygen desaturation index as sleep medicine defines it. It is
    an observation from a consumer sensor on a finger, not a diagnosis, and a
    single night says very little either way.
    """
    if len(points) < BASELINE_MINUTES // minutes + 2:
        return {"events": [], "index": None, "lowest": None}

    values = [p["value"] for p in points]
    window = max(BASELINE_MINUTES // minutes, 2)
    events: List[Dict[str, Any]] = []
    in_event = False
    lowest_seen = None

    for index in range(window, len(values)):
        baseline = median(values[index - window : index])
        value = values[index]
        if not in_event and value <= baseline - DESATURATION_DROP:
            in_event = True
            lowest_seen = value
            events.append(
                {
                    "t": points[index]["t"],
                    "baseline": round(baseline, 1),
                    "lowest": value,
                    "drop": round(baseline - value, 1),
                }
            )
        elif in_event:
            if lowest_seen is None or value < lowest_seen:
                lowest_seen = value
                events[-1]["lowest"] = value
                events[-1]["drop"] = round(events[-1]["baseline"] - value, 1)
            if value >= baseline - RECOVERY_MARGIN:
                in_event = False
                lowest_seen = None

    hours = len(values) * minutes / 60.0
    return {
        "events": events,
        "index": round(len(events) / hours, 1) if hours > 0 else None,
        "lowest": min(values),
    }


def load_calibration() -> Dict[str, Any]:
    """The fitted curve, or the textbook one when nothing has been fitted."""
    path = get_user_data_dir() / CALIBRATION_FILE
    try:
        blob = json.loads(path.read_text())
        return {
            "a": float(blob["a"]),
            "b": float(blob["b"]),
            "nights": blob.get("nights", 0),
            "error": blob.get("error"),
            "fitted": True,
        }
    except Exception:
        return {"a": DEFAULT_A, "b": DEFAULT_B, "nights": 0, "fitted": False}


def estimate(ratios: List[int], calibration: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Saturation for a set of R readings, or None if there are too few."""
    if len(ratios) < MIN_RATIOS_PER_NIGHT:
        return None
    calibration = calibration or load_calibration()
    value = calibration["a"] - calibration["b"] * mean(ratios)
    # A pulse oximeter that reports 103% is broken, not remarkable.
    return round(value, 1) if 70.0 <= value <= 100.0 else None


def _paired_nights(db: Session) -> List[Tuple[str, float, float]]:
    """(day, Oura's SpO2, our mean R) for every night that has both."""
    out: List[Tuple[str, float, float]] = []
    for session in db.query(SleepSession).order_by(SleepSession.day).all():
        if not session.bedtime_start or not session.bedtime_end:
            continue
        daily = db.query(Sleep).filter(Sleep.day == session.day).one_or_none()
        if daily is None or daily.average_spo2 is None:
            continue
        ratios = ratios_between(db, session.bedtime_start, session.bedtime_end)
        if len(ratios) < MIN_RATIOS_PER_NIGHT:
            continue
        out.append((str(session.day), daily.average_spo2, mean(ratios)))
    return out


def _least_squares(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """A and B for SpO2 = A - B*R."""
    if len(points) < 2:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mx, my = mean(xs), mean(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / denominator
    return my - slope * mx, -slope


def fit_calibration(db: Session, save: bool = True) -> Dict[str, Any]:
    """Fit the curve to the paired nights, scored leave-one-night-out."""
    nights = _paired_nights(db)
    if len(nights) < MIN_NIGHTS_TO_FIT:
        return {"fitted": False, "reason": f"only {len(nights)} paired nights"}

    points = [(ratio, spo2) for _, spo2, ratio in nights]
    coefficients = _least_squares(points)
    if coefficients is None:
        return {"fitted": False, "reason": "R does not vary across these nights"}
    a, b = coefficients

    errors = []
    for index in range(len(points)):
        rest = points[:index] + points[index + 1 :]
        held = _least_squares(rest)
        if held is None:
            continue
        errors.append(held[0] - held[1] * points[index][0] - points[index][1])

    result = {
        "fitted": True,
        "a": round(a, 3),
        "b": round(b, 5),
        "nights": len(nights),
        "error": round(sum(abs(e) for e in errors) / len(errors), 3) if errors else None,
        "bias": round(sum(errors) / len(errors), 3) if errors else None,
        "days": [day for day, _, _ in nights],
        "fitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if save:
        (get_user_data_dir() / CALIBRATION_FILE).write_text(json.dumps(result))
    return result


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    from ..database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        result = fit_calibration(db)
        if not result.get("fitted"):
            logger.info("not fitted: %s", result.get("reason"))
            return 1
        logger.info(
            "SpO2 = %.2f - %.4f * R over %d nights "
            "(leave-one-out error %.2f%%, bias %+.2f)",
            result["a"], result["b"], result["nights"],
            result["error"] or 0.0, result["bias"] or 0.0,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
