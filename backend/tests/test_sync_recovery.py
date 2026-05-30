"""Tests for stuck-sync recovery."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.src import sync_recovery as sr_module
from backend.src.sync_recovery import recover_stuck_sync_if_needed


@pytest.fixture()
def patch_config(monkeypatch):
    store: dict = {}

    def _get():
        return dict(store)

    def _update(**kwargs):
        store.update(kwargs)

    monkeypatch.setattr(sr_module.config_manager, "get_config", _get)
    monkeypatch.setattr(sr_module.config_manager, "update_status", lambda status, **kw: _update(status=status, **kw))
    monkeypatch.setattr(sr_module.config_manager, "update_config", _update)
    return store


def test_recovers_processing_status_after_timeout(patch_config):
    old = datetime.now() - timedelta(minutes=30)
    patch_config.update({
        "status": "Processing",
        "status_started_at": old.strftime("%Y-%m-%d %H:%M:%S"),
    })

    assert recover_stuck_sync_if_needed() is True
    assert patch_config["status"] == "Idle"
    assert "timed out" in patch_config["message"]


def test_does_not_recover_recent_processing(patch_config):
    recent = datetime.now() - timedelta(minutes=2)
    patch_config.update({
        "status": "Processing",
        "status_started_at": recent.strftime("%Y-%m-%d %H:%M:%S"),
    })

    assert recover_stuck_sync_if_needed() is False
    assert patch_config["status"] == "Processing"
