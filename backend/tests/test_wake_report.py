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
