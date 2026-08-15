"""Verify ring coverage instead of trusting "caught up".

Twice now a drain has reported success while silently losing days: once when
the frame splitter glued events together, once when a live event leapt the
cursor over four days of unread history. Both times `bytes_left` reached zero
and the app said "caught up", because the ring was answering honestly about a
position the phone had already skipped past.

The check that would have caught both is the same one that matters for the
model: for every night Oura scored, do we actually hold ring events covering
it? A scored session with no ring data is unambiguous — the ring was worn and
recording, so the data existed and we failed to collect it.

    python -m backend.src.ring_events.audit
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import RingEventRaw, SleepSession
from .night import ring_clock_offset, to_ring_ds, to_unix

logger = logging.getLogger("RingAudit")

# A session counts as covered when this share of its five-minute buckets hold
# at least one ring event. Below it there is not enough to stage a night.
MIN_COVERED_FRACTION = 0.5
BUCKET_SECONDS = 300
# The ring stops recording while charging, so short holes are ordinary. Only
# report gaps long enough to swallow a night.
GAP_HOURS = 6.0
# Oura scores short naps as sessions too. They are not what the model trains
# on and often have no ring coverage at all, so counting them as failures
# would mean alerting every night about something not worth fixing. Reported,
# but not counted. 30 five-minute epochs is 2.5 hours.
MIN_LABELS_FOR_A_NIGHT = 30


def _stamp(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()


def coverage_report(db: Session) -> Dict[str, Any]:
    """What we hold against what Oura says exists."""
    offset = ring_clock_offset(db)
    if offset is None:
        return {
            "status": "unaligned",
            "message": "no time_sync events; ring events cannot be placed in time",
            "sessions": [],
            "gaps": [],
        }

    stamps = sorted(
        row[0] for row in db.query(RingEventRaw.timestamp).all()
    )
    if not stamps:
        return {
            "status": "empty",
            "message": "no ring events stored",
            "sessions": [],
            "gaps": [],
        }

    # Bucket occupancy, so a session's coverage is a share of its span rather
    # than a raw count — a thousand events in one minute is not a covered night.
    occupied = {int(to_unix(t, offset) // BUCKET_SECONDS) for t in stamps}

    sessions: List[Dict[str, Any]] = []
    for session in (
        db.query(SleepSession).order_by(SleepSession.day, SleepSession.bedtime_start).all()
    ):
        if not session.bedtime_start or not session.bedtime_end:
            continue
        if not session.sleep_phase_5_min:
            continue
        start = session.bedtime_start.replace(tzinfo=timezone.utc)
        end = session.bedtime_end.replace(tzinfo=timezone.utc)
        first = int(start.timestamp() // BUCKET_SECONDS)
        last = int(end.timestamp() // BUCKET_SECONDS)
        total = max(last - first, 1)
        held = sum(1 for bucket in range(first, last) if bucket in occupied)
        fraction = round(held / total, 3)
        labels = len(session.sleep_phase_5_min)
        sessions.append(
            {
                "day": str(session.day),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "labels": labels,
                "covered_fraction": fraction,
                "covered": fraction >= MIN_COVERED_FRACTION,
                "counted": labels >= MIN_LABELS_FOR_A_NIGHT,
            }
        )

    gaps: List[Dict[str, Any]] = []
    threshold = GAP_HOURS * 36_000  # hours → deciseconds
    for earlier, later in zip(stamps, stamps[1:]):
        if later - earlier > threshold:
            gaps.append(
                {
                    "from": _stamp(to_unix(earlier, offset)),
                    "to": _stamp(to_unix(later, offset)),
                    "hours": round((later - earlier) / 36_000, 1),
                }
            )
    gaps.sort(key=lambda g: -g["hours"])

    counted = [s for s in sessions if s["counted"]]
    missing = [s for s in counted if not s["covered"]]
    return {
        "status": "gaps" if missing else "ok",
        "message": (
            f"{len(missing)} of {len(counted)} scored nights have no ring data"
            if missing
            else f"all {len(counted)} scored nights are covered"
        ),
        "from": _stamp(to_unix(stamps[0], offset)),
        "to": _stamp(to_unix(stamps[-1], offset)),
        "events": len(stamps),
        "sessions": sessions,
        "missing_sessions": [s["day"] for s in missing],
        "gaps": gaps[:10],
        "largest_gap_hours": gaps[0]["hours"] if gaps else 0.0,
    }


def resume_cursor_for_gaps(db: Session, report: Dict[str, Any]) -> Optional[int]:
    """Where to rewind the drain so it re-reads the earliest uncovered night.

    A cursor sitting past a gap is why the ring reports nothing left: it is
    answering about a position beyond the missing data.
    """
    offset = ring_clock_offset(db)
    if offset is None or not report.get("missing_sessions"):
        return None
    earliest = min(
        datetime.fromisoformat(s["start"])
        for s in report["sessions"]
        if s.get("counted") and not s["covered"]
    )
    return to_ring_ds(earliest, offset)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alert", action="store_true", help="Push a notification when nights are missing."
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        report = coverage_report(db)
        logger.info("%s: %s", report["status"], report["message"])
        if report.get("events"):
            logger.info(
                "  %d events, %s → %s", report["events"], report["from"], report["to"]
            )
        for session in report.get("sessions", []):
            if not session["counted"]:
                mark = "nap"
            elif session["covered"]:
                mark = "ok"
            else:
                mark = "MISS"
            logger.info(
                "  %s %-5s %3d labels  coverage %5.1f%%",
                session["day"], mark, session["labels"],
                session["covered_fraction"] * 100,
            )
        for gap in report.get("gaps", []):
            logger.info("  gap %5.1f h  %s → %s", gap["hours"], gap["from"], gap["to"])

        if report["status"] == "gaps":
            cursor = resume_cursor_for_gaps(db, report)
            if cursor is not None:
                logger.info("  rewind the drain cursor to %d to re-read them", cursor)
            if args.alert:
                from ..notify import notify

                notify(db, "Ouracle: ring data missing", report["message"])
            return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
