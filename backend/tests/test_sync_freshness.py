"""Unit tests for the sync freshness read model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.src.insights import sync_freshness as sf_module
from backend.src.insights.sync_freshness import (
    build_sync_freshness,
    data_lag_days,
    expected_latest_day,
    ingest_advanced_data,
)
from backend.src.models import Sleep


@pytest.fixture()
def patch_config(monkeypatch):
    def _apply(values):
        monkeypatch.setattr(
            sf_module.config_manager,
            "get_config",
            lambda: dict(values),
        )

    return _apply


def test_expected_latest_day_is_yesterday():
    today = date(2026, 5, 29)
    assert expected_latest_day(today) == date(2026, 5, 28)


def test_data_lag_ignores_tonights_sleep():
    today = date(2026, 5, 29)
    latest = date(2026, 5, 28)
    assert data_lag_days(latest, today) == 0


def test_ingest_advanced_data():
    assert ingest_advanced_data(date(2026, 5, 26), date(2026, 5, 28))
    assert not ingest_advanced_data(date(2026, 5, 28), date(2026, 5, 28))


def test_empty_database_reports_empty_status(db_session, patch_config):
    patch_config({"status": "Idle"})
    fresh = build_sync_freshness(db_session)
    assert fresh.status == "empty"
    assert fresh.latest_day is None
    assert fresh.days_behind is None
    assert "No Oura data" in (fresh.message or "")


def test_recent_day_reports_fresh(db_session, patch_config):
    yesterday = date.today() - timedelta(days=1)
    db_session.add(Sleep(id="s", day=yesterday, score=80))
    db_session.commit()
    patch_config({"status": "Idle", "last_run": "2025-01-01T00:00:00"})

    fresh = build_sync_freshness(db_session)
    assert fresh.status == "fresh"
    assert fresh.latest_day == yesterday.isoformat()
    assert fresh.days_behind == 0
    assert fresh.last_ingest_at == "2025-01-01T00:00:00"


def test_stale_data_reports_stale_status(db_session, patch_config):
    stale_day = date.today() - timedelta(days=3)
    db_session.add(Sleep(id="s", day=stale_day, score=80))
    db_session.commit()
    patch_config({"status": "Idle"})

    fresh = build_sync_freshness(db_session)
    assert fresh.status == "stale"
    assert fresh.days_behind == 2


def test_very_stale_when_many_days_missing(db_session, patch_config):
    stale_day = date.today() - timedelta(days=6)
    db_session.add(Sleep(id="s", day=stale_day, score=80))
    db_session.commit()
    patch_config({"status": "Idle"})

    fresh = build_sync_freshness(db_session)
    assert fresh.status == "very_stale"
    assert fresh.days_behind == 5


def test_otp_needed_reports_blocked_status(db_session, patch_config):
    patch_config({"status": "otp_needed"})
    fresh = build_sync_freshness(db_session)
    assert fresh.status == "blocked"
    assert "OTP" in (fresh.message or "")


def test_mobile_server_state_is_surfaced(db_session, patch_config):
    patch_config({"status": "Idle", "mobile_sync_enabled": True})

    class _State:
        running = True
        status = None

    fresh = build_sync_freshness(db_session, mobile_server_state=_State())
    assert fresh.mobile_server_enabled is True
    assert fresh.mobile_server_status == "Running"
