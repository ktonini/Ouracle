"""Tests for curated interesting-correlation discovery."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.src.analysis.interesting_correlations import find_interesting_correlations
from backend.src.models import Readiness, SleepSession


def _seed_bedtime_readiness(db, days: int = 30) -> tuple[date, date]:
    """Bedtime(D) anti-correlates with readiness(D+1) — strong lag-1 signal."""
    end = date(2025, 6, 30)
    start = end - timedelta(days=days - 1)
    for offset in range(days):
        d = start + timedelta(days=offset)
        bt_hour = 22 + (offset % 4)
        db.add(
            SleepSession(
                id=f"ss-{d.isoformat()}",
                day=d,
                type="long_sleep",
                bedtime_start=datetime(d.year, d.month, d.day, bt_hour % 24, 0),
                total_sleep_duration=7 * 3600,
                average_hrv=50,
            )
        )
        next_day = d + timedelta(days=1)
        db.add(
            Readiness(
                id=f"r-{next_day.isoformat()}",
                day=next_day,
                score=90 - (offset % 4) * 8,
            )
        )
    db.commit()
    return start, end


def test_finds_bedtime_readiness_candidate(db_session):
    start, end = _seed_bedtime_readiness(db_session, days=30)
    results = find_interesting_correlations(db_session, start, end)
    assert len(results) >= 1
    top = results[0]
    assert top.x_metric == "sleep_session.bedtime_start_minutes"
    assert top.y_metric == "readiness.score"
    assert top.lag_days == 1
    assert top.coefficient is not None
    assert top.coefficient < 0
    assert top.sample_count >= 21
    assert top.x_label
    assert top.y_label
    assert "bedtime" in top.reason.lower() or "Bedtime" in top.reason
    assert top.interpretation


def test_filters_weak_correlations(db_session):
    """Flat readiness scores yield no meaningful correlation above the threshold."""
    end = date(2025, 6, 30)
    start = end - timedelta(days=29)
    for offset in range(30):
        d = start + timedelta(days=offset)
        db_session.add(
            SleepSession(
                id=f"ss-{d.isoformat()}",
                day=d,
                type="long_sleep",
                bedtime_start=datetime(d.year, d.month, d.day, (22 + (offset % 4)) % 24, 0),
                total_sleep_duration=7 * 3600,
            )
        )
        db_session.add(Readiness(id=f"r-{d.isoformat()}", day=d, score=80))
    db_session.commit()
    results = find_interesting_correlations(db_session, start, end, min_abs=0.25)
    assert results == []


def test_filters_low_sample_counts(db_session):
    start, end = _seed_bedtime_readiness(db_session, days=12)
    results = find_interesting_correlations(db_session, start, end, min_samples=21)
    assert results == []
