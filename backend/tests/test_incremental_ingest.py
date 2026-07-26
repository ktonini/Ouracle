"""Tests for incremental ZIP ingest."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from backend.src.ingestion.key_migration import normalize_keys_if_needed
from backend.src.ingestion.runner import ingest_zip_blocking
from backend.src.ingestion.state import get_state, synthetic_id
from backend.src.insights.sync_freshness import apply_post_ingest_outcome
from backend.src.models import HeartRate, Sleep
from backend.tests.helpers.oura_export import (
    minimal_activity_csv,
    minimal_heartrate_csv,
    minimal_readiness_csv,
    minimal_sleep_csv,
    write_export_dir,
    zip_directory,
)


@pytest.fixture()
def patch_incremental_config(monkeypatch):
    store = {
        "incremental_ingest_enabled": True,
        "incremental_reprocess_window_days": 3,
    }

    monkeypatch.setattr(
        "backend.src.ingestion.runner.config_manager.get_config",
        lambda: dict(store),
    )
    return store


def _make_zip(tmp_path: Path, day: str, score: int = 80) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    write_export_dir(
        export_dir,
        dailysleep=minimal_sleep_csv(day, score),
        dailyactivity=minimal_activity_csv(day, score - 5),
        dailyreadiness=minimal_readiness_csv(day, score - 3),
    )
    zip_path = tmp_path / "export.zip"
    zip_directory(export_dir, zip_path)
    return str(zip_path)


def test_deterministic_day_key_stable():
    d = date(2026, 5, 1)
    assert synthetic_id("sleep", [d]) == synthetic_id("sleep", [d])


def test_identical_reingest_skips_zip(db_session, tmp_path, patch_incremental_config):
    normalize_keys_if_needed(db_session)
    zip_path = _make_zip(tmp_path, "2026-05-01")
    first = ingest_zip_blocking(zip_path, db=db_session)
    assert first.advanced
    assert db_session.query(Sleep).count() == 1

    db_session.expire_all()
    second = ingest_zip_blocking(zip_path, db=db_session)
    assert second.skipped_identical_zip
    assert not second.advanced
    db_session.expire_all()
    assert db_session.query(Sleep).count() == 1


def test_one_new_day_advances(db_session, tmp_path, patch_incremental_config):
    normalize_keys_if_needed(db_session)
    zip1 = _make_zip(tmp_path, "2026-05-01")
    ingest_zip_blocking(zip1, db=db_session)

    zip2 = _make_zip(tmp_path / "b", "2026-05-02")
    outcome = ingest_zip_blocking(zip2, db=db_session)
    assert outcome.advanced
    assert db_session.query(Sleep).count() == 2


def test_correction_updates_without_new_day(db_session, tmp_path, patch_incremental_config):
    normalize_keys_if_needed(db_session)
    zip1 = _make_zip(tmp_path, "2026-05-01", score=80)
    ingest_zip_blocking(zip1, db=db_session)

    zip2 = _make_zip(tmp_path / "b", "2026-05-01", score=55)
    outcome = ingest_zip_blocking(zip2, db=db_session)
    assert not outcome.advanced
    assert outcome.changed
    row = db_session.query(Sleep).filter(Sleep.day == date(2026, 5, 1)).one()
    assert row.score == 55


def test_post_ingest_corrections_message(monkeypatch):
    from backend.src.insights import sync_freshness as sf_module
    from backend.src.ingestion.state import IngestOutcome

    store: dict = {}
    monkeypatch.setattr(sf_module.config_manager, "get_config", lambda: dict(store))
    monkeypatch.setattr(
        sf_module.config_manager,
        "update_status",
        lambda status, **kw: store.update({"status": status, **kw}),
    )
    apply_post_ingest_outcome(
        IngestOutcome(
            before_latest=date(2026, 5, 1),
            after_latest=date(2026, 5, 1),
            updated=2,
            inserted=0,
        )
    )
    assert "Updated 2 existing" in store["message"]
    assert store.get("last_run") is not None


def test_fingerprints_recorded_after_first_ingest(db_session, tmp_path, patch_incremental_config):
    normalize_keys_if_needed(db_session)
    zip_path = _make_zip(tmp_path, "2026-05-01")
    ingest_zip_blocking(zip_path, db=db_session)
    assert get_state(db_session, "last_zip_fingerprint") is not None
    assert get_state(db_session, "file_fingerprints") is not None


def test_incremental_heartrate_handles_timezone_aware_csv(db_session, tmp_path, patch_incremental_config):
    """Regression: naive DB high-water marks vs timezone-aware export timestamps."""
    normalize_keys_if_needed(db_session)
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    write_export_dir(
        export_dir,
        dailysleep=minimal_sleep_csv("2026-05-01"),
        dailyactivity=minimal_activity_csv("2026-05-01"),
        dailyreadiness=minimal_readiness_csv("2026-05-01"),
        heartrate=minimal_heartrate_csv(
            [
                ("2026-05-01T10:00:00", 60),
                ("2026-05-01T11:00:00", 62),
            ]
        ),
    )
    zip1 = export_dir.parent / "export1.zip"
    zip_directory(export_dir, zip1)
    ingest_zip_blocking(str(zip1), db=db_session)
    assert db_session.query(HeartRate).count() == 2

    export_dir2 = tmp_path / "export2"
    export_dir2.mkdir(parents=True, exist_ok=True)
    write_export_dir(
        export_dir2,
        dailysleep=minimal_sleep_csv("2026-05-01"),
        dailyactivity=minimal_activity_csv("2026-05-01"),
        dailyreadiness=minimal_readiness_csv("2026-05-01"),
        heartrate=minimal_heartrate_csv(
            [
                ("2026-05-01T10:00:00+00:00", 60),
                ("2026-05-01T11:00:00+00:00", 62),
                ("2026-05-01T12:00:00Z", 64),
            ]
        ),
    )
    zip2 = export_dir2.parent / "export2.zip"
    zip_directory(export_dir2, zip2)
    outcome = ingest_zip_blocking(str(zip2), db=db_session)
    assert outcome.error is None
    assert db_session.query(HeartRate).count() == 3
