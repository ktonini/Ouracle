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
from typing import Dict, List, Optional

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

    Computed from the ring's own inter-beat intervals, so it does not depend on
    Oura having scored the night.
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

        intervals = collect_intervals(db)
        if intervals:
            value = rmssd(intervals)
            beats = [i for i in intervals if 300 <= i <= 2000]
            logger.info(
                "%d beats decoded; RMSSD %s ms, mean HR %.0f bpm",
                len(beats),
                value,
                60_000 / (sum(beats) / len(beats)),
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
