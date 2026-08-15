"""Verifying ring coverage rather than trusting "caught up"."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.models import Base, RingEventRaw, SleepSession
from backend.src.ring_events.audit import coverage_report, resume_cursor_for_gaps
from backend.src.ring_events.night import to_ring_ds

EPOCH = 1_700_000_000.0


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _sync(db):
    """A time_sync event, without which nothing can be placed in time."""
    db.add(
        RingEventRaw(
            id="42-0", tag=0x42, timestamp=0, body="",
            decoded={"unix_time": EPOCH},
        )
    )
    db.commit()


def _session(db, day, start, hours, labels=60):
    db.add(
        SleepSession(
            id=f"s-{day}", day=date.fromisoformat(day),
            bedtime_start=start.replace(tzinfo=None),
            bedtime_end=(start + timedelta(hours=hours)).replace(tzinfo=None),
            sleep_phase_5_min="2" * labels,
        )
    )
    db.commit()


def _cover(db, start, hours, every_minutes=5, tag=0x60):
    """Ring events every `every_minutes` across a window."""
    steps = int(hours * 60 / every_minutes)
    for step in range(steps):
        when = start + timedelta(minutes=step * every_minutes)
        ds = to_ring_ds(when, EPOCH)
        db.add(
            RingEventRaw(id=f"{tag:02x}-{ds}", tag=tag, timestamp=ds, body="00")
        )
    db.commit()


def test_no_time_sync_means_nothing_can_be_placed(db_session):
    report = coverage_report(db_session)
    assert report["status"] == "unaligned"


def test_an_empty_database_reports_unaligned(db_session):
    """Alignment depends on a time_sync event, which is itself a ring event —
    so "no events at all" surfaces as unaligned rather than empty."""
    assert coverage_report(db_session)["status"] == "unaligned"
    assert coverage_report(db_session)["sessions"] == []


def test_a_fully_covered_night_passes(db_session):
    _sync(db_session)
    start = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-09", start, 7)
    _cover(db_session, start, 7)

    report = coverage_report(db_session)
    assert report["status"] == "ok"
    assert report["missing_sessions"] == []
    assert report["sessions"][0]["covered"] is True
    assert report["sessions"][0]["covered_fraction"] > 0.9


def test_a_scored_night_with_no_ring_data_is_caught(db_session):
    """The exact failure the drain reported as "caught up" twice."""
    _sync(db_session)
    covered = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-09", covered, 7)
    _cover(db_session, covered, 7)
    # Oura scored this one, but we hold nothing for it.
    _session(db_session, "2026-08-12", datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc), 7)

    report = coverage_report(db_session)
    assert report["status"] == "gaps"
    assert report["missing_sessions"] == ["2026-08-12"]
    assert "1 of 2" in report["message"]


def test_a_burst_of_events_is_not_a_covered_night(db_session):
    """A thousand events in one minute is not coverage — the check is a share
    of the night's span, not a raw count."""
    _sync(db_session)
    start = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-09", start, 7)
    for i in range(500):
        ds = to_ring_ds(start + timedelta(seconds=i // 10), EPOCH)
        db_session.add(
            RingEventRaw(id=f"60-{ds}-{i}", tag=0x60, timestamp=ds, body="00")
        )
    db_session.commit()

    report = coverage_report(db_session)
    assert report["status"] == "gaps"
    assert report["sessions"][0]["covered"] is False


def test_long_holes_are_reported_but_short_ones_are_not(db_session):
    """The ring stops recording on the charger, so short holes are ordinary."""
    _sync(db_session)
    start = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)
    _cover(db_session, start, 2)
    # A two-hour hole, then a 24-hour one.
    _cover(db_session, start + timedelta(hours=4), 2)
    _cover(db_session, start + timedelta(hours=30), 2)

    report = coverage_report(db_session)
    hours = [g["hours"] for g in report["gaps"]]
    assert any(h > 20 for h in hours)
    assert not any(h < 6 for h in hours)


def test_rewind_points_at_the_earliest_missing_night(db_session):
    _sync(db_session)
    _session(db_session, "2026-08-12", datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc), 7)
    _session(db_session, "2026-08-13", datetime(2026, 8, 13, 22, 0, tzinfo=timezone.utc), 7)
    _cover(db_session, datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc), 7)

    report = coverage_report(db_session)
    cursor = resume_cursor_for_gaps(db_session, report)
    expected = to_ring_ds(datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc), EPOCH)
    assert cursor == expected


def test_rewind_is_none_when_nothing_is_missing(db_session):
    _sync(db_session)
    start = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-09", start, 7)
    _cover(db_session, start, 7)
    report = coverage_report(db_session)
    assert resume_cursor_for_gaps(db_session, report) is None


def test_short_naps_are_reported_but_not_counted_as_failures(db_session):
    """Oura scores naps as sessions. They are not what the model trains on and
    often have no ring coverage, so counting them would alert forever."""
    _sync(db_session)
    start = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-09", start, 7)
    _cover(db_session, start, 7)
    # A 25-minute nap with nothing behind it.
    _session(db_session, "2026-08-10", datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc),
             0.4, labels=5)

    report = coverage_report(db_session)
    assert report["status"] == "ok"
    assert report["missing_sessions"] == []
    nap = [s for s in report["sessions"] if s["day"] == "2026-08-10"][0]
    assert nap["counted"] is False
    assert nap["covered"] is False  # still visible, just not a failure
    assert "1 scored nights" in report["message"] or "all 1" in report["message"]


def test_rewind_skips_naps_and_targets_a_real_night(db_session):
    """Rewinding to a nap would re-drain a week to recover 25 minutes."""
    _sync(db_session)
    _session(db_session, "2026-08-06", datetime(2026, 8, 6, 2, 0, tzinfo=timezone.utc),
             0.4, labels=5)
    real = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    _session(db_session, "2026-08-12", real, 7)
    _cover(db_session, datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc), 7)

    report = coverage_report(db_session)
    assert report["missing_sessions"] == ["2026-08-12"]
    assert resume_cursor_for_gaps(db_session, report) == to_ring_ds(real, EPOCH)
