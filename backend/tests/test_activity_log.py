from __future__ import annotations

import shutil
from pathlib import Path

from backend.src.activity_log import append_activity, clear_activity, read_activity
from backend.src.config import WAITING_FOR_EXPORT_STATUS, ConfigManager
from backend.src.export_wait import mark_waiting_for_export


def _sandbox(name: str) -> Path:
    root = Path("backend") / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def test_activity_log_append_and_newest_first(monkeypatch):
    tmp_path = _sandbox(".test-tmp-activity-1")
    monkeypatch.setattr("backend.src.activity_log.get_user_data_dir", lambda: tmp_path)
    clear_activity()
    append_activity("first", category="sync")
    append_activity("second", level="success", category="export")
    entries = read_activity(limit=10)
    assert [e["message"] for e in entries] == ["second", "first"]
    assert entries[0]["level"] == "success"
    assert entries[0]["category"] == "export"
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_activity_log_trims_to_max(monkeypatch):
    tmp_path = _sandbox(".test-tmp-activity-2")
    monkeypatch.setattr("backend.src.activity_log.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.src.activity_log.MAX_ENTRIES", 5)
    clear_activity()
    for i in range(8):
        append_activity(f"event-{i}")
    entries = read_activity(limit=20)
    assert len(entries) == 5
    assert entries[0]["message"] == "event-7"
    assert entries[-1]["message"] == "event-3"
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_update_status_writes_activity(monkeypatch):
    tmp_path = _sandbox(".test-tmp-activity-3")
    monkeypatch.setattr("backend.src.paths.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.src.activity_log.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.src.config.get_user_data_dir", lambda: tmp_path)
    clear_activity()
    manager = ConfigManager()
    manager.update_status("Running Automation...", message="Checking for a ready export...")
    manager.update_status(
        WAITING_FOR_EXPORT_STATUS,
        message="Oura is generating an export.",
        logged_in=True,
    )
    entries = read_activity()
    assert any("generating an export" in e["message"] for e in entries)
    assert manager.get_config()["status"] == WAITING_FOR_EXPORT_STATUS
    assert manager.get_config()["logged_in"] is True
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_mark_waiting_for_export_sets_durable_status(monkeypatch):
    tmp_path = _sandbox(".test-tmp-activity-4")
    monkeypatch.setattr("backend.src.paths.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.src.activity_log.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("backend.src.config.get_user_data_dir", lambda: tmp_path)
    clear_activity()
    from backend.src import config as config_mod
    from backend.src import export_wait as export_wait_mod

    manager = ConfigManager()
    monkeypatch.setattr(config_mod, "config_manager", manager)
    monkeypatch.setattr(export_wait_mod, "config_manager", manager)

    mark_waiting_for_export(requested_now=True)
    cfg = manager.get_config()
    assert cfg["status"] == WAITING_FOR_EXPORT_STATUS
    assert cfg["last_export_request_at"]
    assert "can take days" in (cfg.get("message") or "")
    entries = read_activity()
    assert any("Export requested" in e["message"] for e in entries)
    shutil.rmtree(tmp_path, ignore_errors=True)
