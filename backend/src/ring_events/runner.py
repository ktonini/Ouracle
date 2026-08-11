"""Decode stored ring events, and derive metrics from them.

Runs over `ring_event_raw`, filling in `decoded`. Safe to re-run: decoding is
idempotent, and `--all` re-decodes everything after a decoder improves — the
reason raw bodies are kept.

    python -m backend.src.ring_events.runner [--all]
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import RingEventRaw
from .decoders import decode_event, decode_name

logger = logging.getLogger("RingEventDecode")


def decode_stored(db: Session, redecode: bool = False, batch_size: int = 2000) -> Dict[str, int]:
    """Decodes events lacking a decode (or all of them). Returns per-name counts."""
    query = db.query(RingEventRaw)
    if not redecode:
        query = query.filter(RingEventRaw.decoded.is_(None))

    counts: Dict[str, int] = {}
    pending = 0
    for row in query.yield_per(batch_size):
        decoded = decode_event(row.tag, bytes.fromhex(row.body)) if row.body else None
        if decoded is None:
            continue
        # Keep the human-readable name alongside, so stored data is legible
        # without consulting the tag table.
        decoded["_event"] = decode_name(row.tag)
        row.decoded = decoded
        counts[decoded["_event"]] = counts.get(decoded["_event"], 0) + 1
        pending += 1
        if pending >= batch_size:
            db.commit()
            pending = 0
    db.commit()
    return counts


def rmssd(intervals: List[int]) -> Optional[float]:
    """Root mean square of successive differences — the standard HRV measure.

    ⚠️ Validated against the ring's own HRV events (tag 0x5d) over the night of
    2026-08-05: mean heart rate matches exactly (68 bpm), but this figure came
    out ~1.5× the ring's own RMSSD (34.9 vs 22.7 ms). The 0x60 IBI magnitudes
    are therefore right while their beat-to-beat differences are not — likely
    ordering within the packet or low-bit noise in that (upstream-unvalidated)
    layout.

    So prefer `ring_reported_hrv()` for HRV; this is useful for relative
    comparisons and for validating future decoder fixes.
    """
    beats = [i for i in intervals if 300 <= i <= 2000]
    if len(beats) < 2:
        return None
    diffs = [b - a for a, b in zip(beats, beats[1:])]
    # Drop implausible jumps between successive beats (missed/spurious beats).
    diffs = [d for d in diffs if abs(d) < 300]
    if not diffs:
        return None
    return round(math.sqrt(sum(d * d for d in diffs) / len(diffs)), 1)


def ring_reported_hrv(db: Session, start: int = 0, end: Optional[int] = None) -> Dict[str, Any]:
    """HRV as the ring itself reports it (tag 0x5d), one value per 5 minutes.

    This is the trustworthy source: averaging these reproduces Oura's nightly
    `average_hrv` exactly (22.7 vs 23 ms on 2026-08-05), which also shows that
    figure is computed on-device rather than in their cloud.
    """
    query = db.query(RingEventRaw).filter(
        RingEventRaw.tag == 0x5D, RingEventRaw.decoded.isnot(None)
    )
    if start:
        query = query.filter(RingEventRaw.timestamp >= start)
    if end is not None:
        query = query.filter(RingEventRaw.timestamp <= end)

    rmssd_values: List[int] = []
    hr_values: List[int] = []
    for row in query.order_by(RingEventRaw.timestamp).all():
        # Zero entries are padding for slots the ring didn't measure.
        rmssd_values.extend(v for v in row.decoded.get("rmssd_ms", []) if v)
        hr_values.extend(v for v in row.decoded.get("hr_bpm", []) if v)
    return {
        "rmssd_ms": rmssd_values,
        "hr_bpm": hr_values,
        "average_rmssd_ms": round(sum(rmssd_values) / len(rmssd_values), 1)
        if rmssd_values
        else None,
        "average_hr_bpm": round(sum(hr_values) / len(hr_values))
        if hr_values
        else None,
        "samples": len(rmssd_values),
    }


def collect_intervals(db: Session, tags=(0x60, 0x80)) -> List[int]:
    """All decoded inter-beat intervals, oldest first."""
    rows = (
        db.query(RingEventRaw)
        .filter(RingEventRaw.tag.in_(tags), RingEventRaw.decoded.isnot(None))
        .order_by(RingEventRaw.timestamp)
        .all()
    )
    intervals: List[int] = []
    for row in rows:
        intervals.extend(row.decoded.get("ibi_ms", []) or [])
    return intervals


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Decode stored ring events.")
    parser.add_argument(
        "--all", action="store_true", help="Re-decode every event, not just new ones."
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        counts = decode_stored(db, redecode=args.all)
        total = sum(counts.values())
        logger.info("Decoded %d events", total)
        for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            logger.info("  %-32s %d", name, count)

        reported = ring_reported_hrv(db)
        if reported["samples"]:
            logger.info(
                "ring-reported HRV: %s ms over %d samples (mean HR %s bpm)",
                reported["average_rmssd_ms"],
                reported["samples"],
                reported["average_hr_bpm"],
            )

        intervals = collect_intervals(db)
        if intervals:
            beats = [i for i in intervals if 300 <= i <= 2000]
            logger.info(
                "%d beats decoded; mean HR %.0f bpm (derived RMSSD %s ms — see caveat)",
                len(beats),
                60_000 / (sum(beats) / len(beats)),
                rmssd(intervals),
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
