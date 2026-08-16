"""Nightly ring figures beside Oura's own."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.models import Base, RingEventRaw, Sleep, SleepSession
from backend.src.ring_events.night import to_ring_ds
from backend.src.ring_events.trends import agreement, nightly_summaries

EPOCH = 1_700_000_000.0


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        RingEventRaw(id="42-0", tag=0x42, timestamp=0, body="",
                     decoded={"unix_time": EPOCH})
    )
    session.commit()
    return session


def _session(db, day, hours=7, longest=True, **fields):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=22)
    db.add(
        SleepSession(
            id=f"s-{day}-{int(longest)}", day=day,
            bedtime_start=start, bedtime_end=start + timedelta(hours=hours),
            total_sleep_duration=int(hours * 3600) if longest else 600,
            sleep_phase_5_min="2" * 60, **fields,
        )
    )
    db.commit()
    return start


def _beats(db, start, hours=7):
    for minute in range(hours * 60):
        ds = to_ring_ds(start + timedelta(minutes=minute), EPOCH)
        db.add(
            RingEventRaw(
                id=f"60-{ds}", tag=0x60, timestamp=ds, body="",
                decoded={"ibi_ms": [1000] * 30},
            )
        )
    db.commit()


def test_a_night_with_no_ring_data_still_reports_the_cloud(db_session):
    """Half a comparison is still worth showing — and hiding it would make a
    gap in the ring look like a gap in the night."""
    day = date.today() - timedelta(days=1)
    _session(db_session, day, deep_sleep_duration=3600, rem_sleep_duration=5400)
    rows = nightly_summaries(db_session, days=7)
    assert len(rows) == 1
    assert rows[0]["ours"] == {}
    assert rows[0]["theirs"]["deep_minutes"] == 60
    assert rows[0]["theirs"]["rem_minutes"] == 90


def test_our_figures_appear_beside_theirs(db_session):
    day = date.today() - timedelta(days=1)
    start = _session(db_session, day, deep_sleep_duration=3600)
    _beats(db_session, start)
    db_session.add(Sleep(id="sl", day=day, score=80, average_spo2=94.0))
    db_session.commit()

    rows = nightly_summaries(db_session, days=7)
    assert rows[0]["ours"]["average_hr"] == 60
    assert rows[0]["ours"]["asleep_minutes"] is not None
    assert rows[0]["theirs"]["score"] == 80
    assert rows[0]["theirs"]["spo2_percent"] == 94.0


def test_only_the_longest_session_of_a_day_is_used(db_session):
    """Naps would otherwise put two points on the same day."""
    day = date.today() - timedelta(days=1)
    _session(db_session, day, hours=7, longest=True)
    _session(db_session, day, hours=1, longest=False)
    rows = nightly_summaries(db_session, days=7)
    assert len(rows) == 1
    assert rows[0]["theirs"]["asleep_minutes"] == 420


def test_window_excludes_older_nights(db_session):
    _session(db_session, date.today() - timedelta(days=2))
    _session(db_session, date.today() - timedelta(days=40))
    assert len(nightly_summaries(db_session, days=7)) == 1
    assert len(nightly_summaries(db_session, days=60)) == 2


def test_agreement_measures_only_nights_that_have_both():
    rows = [
        {"day": "a", "ours": {"breath_rate": 12.5}, "theirs": {"breath_rate": 12.0}},
        {"day": "b", "ours": {"breath_rate": 13.0}, "theirs": {"breath_rate": 12.0}},
        {"day": "c", "ours": {}, "theirs": {"breath_rate": 12.0}},
        {"day": "d", "ours": {"breath_rate": 12.0}, "theirs": {}},
    ]
    result = agreement(rows)
    assert result["breath_rate"]["nights"] == 2
    assert result["breath_rate"]["mean_abs_difference"] == pytest.approx(0.75)
    assert result["breath_rate"]["bias"] == pytest.approx(0.75)


def test_agreement_omits_a_metric_neither_side_has():
    assert agreement([{"day": "a", "ours": {}, "theirs": {}}]) == {}
