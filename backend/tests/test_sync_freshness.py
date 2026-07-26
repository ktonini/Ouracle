"""Unit tests for the sync freshness read model."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.src.insights import sync_freshness as sf_module
from backend.src.insights.sync_freshness import (
    apply_post_ingest_result,
    build_sync_freshness,
    data_lag_days,
    expected_latest_day,
    ingest_advanced_data,
)
from backend.src.models import Sleep


@pytest.fixture()
def patch_config(monkeypatch):
    store: dict = {}

    def _apply(values):
        store.clear()
        store.update(values)

    monkeypatch.setattr(sf_module.config_manager, "get_config", lambda: dict(store))
    monkeypatch.setattr(
        sf_module.config_manager,
        "update_status",
        lambda status, **kw: store.update({"status": status, **kw}),
    )
    monkeypatch.setattr(sf_module.config_manager, "update_config", lambda **kw: store.update(kw))
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


def test_fresh_status_replaces_stale_no_new_days_message(db_session, patch_config):
    yesterday = date.today() - timedelta(days=1)
    db_session.add(Sleep(id="s", day=yesterday, score=80))
    db_session.commit()
    patch_config(
        {
            "status": "Idle",
            "message": (
                "Ingest finished but no new days were added. "
                "Request a fresh Oura export and sync again."
            ),
        }
    )

    fresh = build_sync_freshness(db_session)
    assert fresh.status == "fresh"
    assert fresh.days_behind == 0
    assert "no new days" not in (fresh.message or "").lower()
    assert "Up to date through" in (fresh.message or "")


def test_post_ingest_no_advance_but_caught_up_is_success(patch_config):
    yesterday = date.today() - timedelta(days=1)
    patch_config({"status": "Processing"})
    apply_post_ingest_result(yesterday, yesterday)
    cfg = sf_module.config_manager.get_config()
    assert cfg["status"] == "Idle"
    assert "already up to date" in cfg["message"].lower()
    assert "no new days were added" not in cfg["message"].lower()


def test_post_ingest_no_advance_and_behind_warns(patch_config):
    stale = date.today() - timedelta(days=5)
    patch_config({"status": "Processing"})
    apply_post_ingest_result(stale, stale)
    cfg = sf_module.config_manager.get_config()
    assert "no new days were added" in cfg["message"].lower()


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


def test_next_run_ignores_stale_persisted_config(db_session, patch_config):
    from datetime import datetime

    from backend.src.scheduling import compute_next_daily_run

    patch_config(
        {
            "status": "Idle",
            "schedule_time": "23:59",
            "next_run": "2020-01-01 00:00:00",
        }
    )
    fresh = build_sync_freshness(db_session)
    expected = compute_next_daily_run(datetime.now(), "23:59").strftime("%Y-%m-%d %H:%M:%S")
    assert fresh.next_run == expected


def test_mobile_server_state_is_surfaced(db_session, patch_config):
    patch_config({"status": "Idle", "mobile_sync_enabled": True})

    class _State:
        running = True
        status = None

    fresh = build_sync_freshness(db_session, mobile_server_state=_State())
    assert fresh.mobile_server_enabled is True
    assert fresh.mobile_server_status == "Running"
