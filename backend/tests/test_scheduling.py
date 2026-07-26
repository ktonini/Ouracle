"""Unit tests for daily auto-sync schedule computation."""

from __future__ import annotations

from datetime import datetime

from backend.src.scheduling import compute_next_daily_run


def test_later_today_returns_today():
    now = datetime(2026, 5, 31, 9, 0, 0)
    nxt = compute_next_daily_run(now, "11:00")
    assert nxt == datetime(2026, 5, 31, 11, 0, 0)


def test_already_passed_returns_tomorrow():
    now = datetime(2026, 5, 31, 12, 0, 0)
    nxt = compute_next_daily_run(now, "11:00")
    assert nxt == datetime(2026, 6, 1, 11, 0, 0)


def test_exact_same_minute_returns_tomorrow():
    now = datetime(2026, 5, 31, 11, 0, 0)
    nxt = compute_next_daily_run(now, "11:00")
    assert nxt == datetime(2026, 6, 1, 11, 0, 0)


def test_invalid_schedule_falls_back_to_11_00():
    now = datetime(2026, 5, 31, 9, 0, 0)
    nxt = compute_next_daily_run(now, "not-a-time")
    assert nxt == datetime(2026, 5, 31, 11, 0, 0)
