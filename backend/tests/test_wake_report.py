"""Wake report: composition, readiness gating, and once-per-day dedup."""

import time
from datetime import date, datetime

from backend.src.models import IngestState, Readiness, Sleep, SleepSession
from backend.src.oura_v2.wake_report import (
    compose_report,
    mark_sent,
    report_for_day,
)

DAY = date(2026, 8, 6)


def _session(**overrides):
    values = dict(
        id="sleep-1",
        day=DAY,
        type="long_sleep",
        bedtime_start=datetime(2026, 8, 5, 23, 32),
        bedtime_end=datetime(2026, 8, 6, 6, 47),
        total_sleep_duration=24120,  # 6h 42m
        deep_sleep_duration=5400,
        rem_sleep_duration=6600,
        average_hrv=55,
        lowest_heart_rate=52,
    )
    values.update(overrides)
    return SleepSession(**values)


def _use_timezone(monkeypatch, name: str):
    """Bedtimes are stored naive-UTC and reported in local time, so these
    assertions must pin the zone rather than inherit the machine's."""
    monkeypatch.setenv("TZ", name)
    time.tzset()


def test_compose_full_report(monkeypatch):
    _use_timezone(monkeypatch, "UTC")
    message = compose_report(
        [_session()],
        Sleep(id="ds-1", day=DAY, score=78),
        Readiness(id="dr-1", day=DAY, score=81),
    )
    assert "You slept 6h 42m" in message
    assert "11:32 PM – 6:47 AM" in message
    assert "Sleep score 78" in message
    assert "Readiness 81" in message
    assert "deep 1h 30m" in message
    assert "HRV 55ms" in message


def test_clock_times_are_local_not_utc(monkeypatch):
    """Regression: a 06:47 UTC wake-up was reported as "1:47 PM"."""
    _use_timezone(monkeypatch, "America/Los_Angeles")
    message = compose_report([_session()], None, None)
    # 23:32 / 06:47 UTC -> 16:32 / 23:47 the previous evening in PDT.
    assert "4:32 PM" in message
    assert "11:47 PM" in message


def test_compose_without_scores_yet():
    message = compose_report([_session()], None, None)
    assert "Score still processing" in message
    assert "Readiness" not in message


def test_report_waits_for_session(db_session):
    assert report_for_day(db_session, DAY) is None


def test_report_ignores_short_naps(db_session):
    db_session.add(_session(total_sleep_duration=1800))  # 30 min nap
    db_session.commit()
    assert report_for_day(db_session, DAY) is None


def test_report_fires_once(db_session):
    db_session.add(_session())
    db_session.commit()

    first = report_for_day(db_session, DAY)
    assert first is not None and "6h 42m" in first
    mark_sent(db_session, DAY)

    assert report_for_day(db_session, DAY) is None
    assert report_for_day(db_session, DAY, force=True) is not None
    assert db_session.get(IngestState, "wake_report:2026-08-06") is not None


def test_report_sums_multiple_sessions(db_session):
    db_session.add(_session())
    db_session.add(
        _session(id="sleep-2", total_sleep_duration=3600, type="sleep")
    )
    db_session.commit()
    message = report_for_day(db_session, DAY)
    assert "7h 42m" in message


def _staged(pattern):
    """`pattern` like 'aaddllrraa' — one letter per five-minute epoch."""
    from datetime import datetime, timedelta, timezone

    names = {"a": "awake", "d": "deep", "l": "light", "r": "rem"}
    start = datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc)
    return [
        {
            "t": (start + timedelta(minutes=5 * i)).isoformat(),
            "stage": names[c],
            "confidence": 0.8,
        }
        for i, c in enumerate(pattern)
    ]


def test_brief_awakenings_do_not_split_the_night():
    """Waking for five minutes at 4am does not end the night."""
    from backend.src.oura_v2.wake_report import _longest_recent_sleep

    block = _longest_recent_sleep(_staged("d" * 20 + "a" + "l" * 20))
    assert len(block) == 41  # one continuous night, the wake absorbed


def test_a_long_awakening_ends_the_block():
    from backend.src.oura_v2.wake_report import _longest_recent_sleep

    block = _longest_recent_sleep(_staged("d" * 40 + "a" * 8 + "l" * 40))
    assert len(block) == 40
    assert block[0]["stage"] == "light"  # the most recent block, not the first


def test_a_nap_is_not_a_night():
    from backend.src.oura_v2.wake_report import _longest_recent_sleep

    assert _longest_recent_sleep(_staged("l" * 12)) == []   # one hour
    assert _longest_recent_sleep(_staged("a" * 40)) == []   # never asleep


def test_ring_report_says_where_the_numbers_came_from(monkeypatch):
    """The ring's own staging is an estimate, not Oura's score, and the message
    must not pretend otherwise."""
    from backend.src.oura_v2 import wake_report

    staged = _staged("d" * 24 + "r" * 12 + "l" * 24)
    monkeypatch.setattr(
        "backend.src.ring_events.night.build_night",
        lambda db, start, end: {"heart_rate": [{"t": "x", "value": 60}], "lowest_hr": 58},
    )
    monkeypatch.setattr(
        "backend.src.ring_events.staging.build_epochs", lambda *a, **k: ["epoch"]
    )
    monkeypatch.setattr(
        "backend.src.ring_events.staging.stage_epochs", lambda epochs: staged
    )

    message = wake_report.ring_report_for_day(None, date(2026, 8, 16))
    assert message is not None
    assert "You slept 5h 00m" in message
    assert "From the ring" in message
    assert "Oura hasn't scored" in message
    assert "deep 2h 00m" in message
    assert "REM 1h 00m" in message
    assert "RHR 58" in message


def test_ring_report_is_none_without_ring_data(monkeypatch):
    from backend.src.oura_v2 import wake_report

    monkeypatch.setattr(
        "backend.src.ring_events.night.build_night",
        lambda db, start, end: {"error": "no time_sync events"},
    )
    assert wake_report.ring_report_for_day(None, date(2026, 8, 16)) is None
