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
import os
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

# Ring-derived fallback. Looked for over this many hours back from now, so it
# works whatever hours you keep — a fixed evening-to-morning window assumes a
# schedule, and gets it wrong for anyone sleeping across UTC midday.
#
# It must comfortably contain the whole of the last sleep however late the
# report runs. At 30 hours it did not: a report at 5pm looked back only to
# noon the day before, so a night that began at 8:35am was clipped and read as
# three hours instead of six.
RING_LOOKBACK_HOURS = 48
# If the block still reaches the start of the window it is probably cut off,
# so try once more with a wider one rather than report a truncated night.
RING_LOOKBACK_RETRY_HOURS = 84
# A block this long is a night. Shorter is a nap, and not what the morning
# report is for.
MIN_RING_SLEEP_MINUTES = 180


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def timezone_warning(
    tz_env: Optional[str], offset: Optional[timedelta]
) -> Optional[str]:
    """Whether this process will silently report UTC clock times.

    Every clock time in a report is a naive-UTC value converted with
    `astimezone()`, and "which day is it" uses the local date. With no zone
    configured both resolve to UTC — the report is still sent, still looks
    well-formed, and is simply hours out.

    A machine with a real local zone is fine even without TZ set; a container,
    which has neither, is not.
    """
    if tz_env:
        return None
    if offset not in (None, timedelta(0)):
        return None
    return (
        "TZ is not set, so times will be reported in UTC. Set TZ (e.g. "
        "TZ=America/Los_Angeles) in the environment file."
    )


def warn_if_timezone_is_unset() -> Optional[str]:
    """Log the above for the environment this process is actually running in."""
    message = timezone_warning(
        os.environ.get("TZ"), datetime.now().astimezone().utcoffset()
    )
    if message:
        logger.warning(message)
    return message


def _fmt_clock(dt: Optional[datetime]) -> Optional[str]:
    """Bedtimes are stored as naive UTC; report them in local time.

    Formatting them directly showed a 06:06 bedtime as "1:06 PM".
    """
    if dt is None:
        return None
    local = dt.replace(tzinfo=timezone.utc).astimezone()
    return local.strftime("%-I:%M %p")


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


def _longest_recent_sleep(staged: List[dict]) -> List[dict]:
    """The most recent run of asleep epochs, ignoring brief awakenings.

    Waking for five minutes at 4am does not end the night, so short awake
    stretches are absorbed rather than splitting the block in two.
    """
    blocks: List[List[dict]] = []
    current: List[dict] = []
    awake_run = 0
    for epoch in staged:
        if epoch["stage"] == "awake":
            awake_run += 1
            if awake_run > 3 and current:  # more than ~15 minutes up
                blocks.append(current)
                current = []
            elif current:
                current.append(epoch)
        else:
            awake_run = 0
            current.append(epoch)
    if current:
        blocks.append(current)

    long_enough = [
        b for b in blocks if len(b) * 5 >= MIN_RING_SLEEP_MINUTES
    ]
    return long_enough[-1] if long_enough else []


def _staged_block(db: Session, hours: int) -> Optional[tuple]:
    """The most recent sleep block within `hours`, plus its night and whether
    it starts at the very edge of the window."""
    from ..ring_events.staging import build_epochs, stage_epochs
    from ..ring_events.night import build_night

    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(hours=hours)
    night = build_night(db, start, end)
    if night.get("error") or not night.get("heart_rate"):
        return None

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
    block = _longest_recent_sleep(staged)
    if not block:
        return None
    # Within an epoch of the first thing we staged: the sleep probably began
    # before the window did.
    clipped = bool(staged) and block[0]["t"] <= staged[0]["t"]
    return block, night, clipped


def ring_report_for_day(db: Session, day: date) -> Optional[str]:
    """A report built from the ring alone, for when Oura hasn't scored yet.

    The whole point of reading the ring directly is not depending on their
    pipeline; a morning push that waits for their scoring still does.
    """
    from ..ring_events.staging import EPOCH_MINUTES

    found = _staged_block(db, RING_LOOKBACK_HOURS)
    if found and found[2]:
        # Reported duration would be short by however much fell outside the
        # window, which is exactly the number the notification leads with.
        logger.info("sleep block reached the window edge; widening the lookback")
        found = _staged_block(db, RING_LOOKBACK_RETRY_HOURS) or found
    if not found:
        return None
    block, night, _ = found

    minutes: dict = {}
    for epoch in block:
        minutes[epoch["stage"]] = minutes.get(epoch["stage"], 0) + EPOCH_MINUTES
    asleep = sum(v for k, v in minutes.items() if k != "awake")

    began = datetime.fromisoformat(block[0]["t"]).replace(tzinfo=None)
    ended = datetime.fromisoformat(block[-1]["t"]).replace(tzinfo=None) + timedelta(
        minutes=EPOCH_MINUTES
    )

    parts = [
        f"You slept {_fmt_duration(asleep * 60)}"
        f" ({_fmt_clock(began)} – {_fmt_clock(ended)})",
        "From the ring — Oura hasn't scored this night yet",
    ]
    detail = [
        f"{name} {_fmt_duration(minutes[key] * 60)}"
        for key, name in (("deep", "deep"), ("rem", "REM"))
        if minutes.get(key)
    ]
    if night.get("lowest_hr"):
        detail.append(f"RHR {night['lowest_hr']}")
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
    warn_if_timezone_is_unset()

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

            # Nothing from the cloud. Fall back to the ring, which already
            # holds the night — waiting on Oura's scoring is the dependency
            # this project exists to remove.
            if db.get(IngestState, MARKER_PREFIX + today.isoformat()) is None or args.force:
                message = ring_report_for_day(db, today)
                if message and notify(db, "Last night", message):
                    mark_sent(db, today)
                    logger.info("Wake report sent for %s from ring data.", today)
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
