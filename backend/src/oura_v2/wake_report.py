"""Morning wake report: notify once when last night's sleep lands.

Runs every 15 minutes in a morning window (systemd timer). Each run does a
light incremental sync of the sleep-related collections, and the first time
a sleep session exists for today, sends a push notification with duration
and scores. A per-day marker in ingest_state guarantees exactly one
notification.

    python -m backend.src.oura_v2.wake_report [--test | --force]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import IngestState, Readiness, Sleep, SleepSession
from ..notify import notify
from .client import OuraV2Client
from .credentials import CredentialError, provider_from_env
from .sync import run_sync

logger = logging.getLogger("WakeReport")

SLEEP_COLLECTIONS = [
    "sleep",
    "daily_sleep",
    "daily_spo2",
    "daily_readiness",
    "daily_stress",
    # Cheap single request; keeps the ring battery reading fresh through
    # the morning window instead of only at the daily sync.
    "ring_battery_level",
]

MARKER_PREFIX = "wake_report:"

# Sessions shorter than this are naps/rest, not the night's sleep.
MIN_SESSION_SECONDS = 60 * 60


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def _fmt_clock(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%-I:%M %p") if dt else None


def compose_report(
    sessions: List[SleepSession],
    sleep_day: Optional[Sleep],
    readiness: Optional[Readiness],
) -> str:
    """Human message for the night. Pure function for testability."""
    main = max(sessions, key=lambda s: s.total_sleep_duration or 0)
    parts: List[str] = []

    duration = sum(s.total_sleep_duration or 0 for s in sessions)
    parts.append(f"You slept {_fmt_duration(duration)}")

    start, end = _fmt_clock(main.bedtime_start), _fmt_clock(main.bedtime_end)
    if start and end:
        parts[0] += f" ({start} – {end})"

    if sleep_day is not None and sleep_day.score is not None:
        parts.append(f"Sleep score {sleep_day.score}")
    else:
        parts.append("Score still processing")

    if readiness is not None and readiness.score is not None:
        parts.append(f"Readiness {readiness.score}")

    detail: List[str] = []
    if main.deep_sleep_duration:
        detail.append(f"deep {_fmt_duration(main.deep_sleep_duration)}")
    if main.rem_sleep_duration:
        detail.append(f"REM {_fmt_duration(main.rem_sleep_duration)}")
    if main.average_hrv:
        detail.append(f"HRV {main.average_hrv}ms")
    if main.lowest_heart_rate:
        detail.append(f"RHR {main.lowest_heart_rate}")
    if detail:
        parts.append(" · ".join(detail))

    return "\n".join(parts)


def report_for_day(db: Session, day: date, force: bool = False) -> Optional[str]:
    """Returns the message to send for ``day``, or None if not ready/already
    sent. Does not commit; caller marks the day after a successful send."""
    marker = db.get(IngestState, MARKER_PREFIX + day.isoformat())
    if marker is not None and not force:
        return None

    sessions = [
        s
        for s in db.query(SleepSession).filter(SleepSession.day == day).all()
        if (s.total_sleep_duration or 0) >= MIN_SESSION_SECONDS
    ]
    if not sessions:
        return None

    sleep_day = db.query(Sleep).filter(Sleep.day == day).one_or_none()
    readiness = db.query(Readiness).filter(Readiness.day == day).one_or_none()
    return compose_report(sessions, sleep_day, readiness)


def mark_sent(db: Session, day: date) -> None:
    key = MARKER_PREFIX + day.isoformat()
    row = db.get(IngestState, key)
    if row is None:
        row = IngestState(key=key)
        db.add(row)
    row.value = datetime.now(timezone.utc).isoformat()
    db.commit()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Morning sleep notification.")
    parser.add_argument(
        "--test", action="store_true", help="Send a test notification and exit."
    )
    parser.add_argument(
        "--force", action="store_true", help="Ignore the already-sent marker."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db

    if args.test:
        init_db()
        db = SessionLocal()
        try:
            ok = notify(db, "Ouracle test", "Wake report is armed. 😴")
        finally:
            db.close()
        print("test notification sent" if ok else "no notification channel worked")
        return 0 if ok else 1

    try:
        client = OuraV2Client(provider_from_env())
        init_db()
        db = SessionLocal()
        try:
            run_sync(db, client, only=SLEEP_COLLECTIONS)
            # Server runs in local time; "today" is the wake-up day. Also try
            # yesterday: Oura sometimes classifies a night hours late, and a
            # night that lands after midnight would otherwise never be
            # reported at all.
            today = datetime.now().date()
            for day in (today, today - timedelta(days=1)):
                message = report_for_day(db, day, force=args.force)
                if message is None:
                    continue
                title = "Last night" if day == today else day.strftime("Night of %a %d %b")
                if notify(db, title, message):
                    mark_sent(db, day)
                    logger.info("Wake report sent for %s.", day)
                return 0

            logger.info("No new sleep to report for %s.", today)
        finally:
            db.close()
    except CredentialError as e:
        logger.critical("Credential failure: %s", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
