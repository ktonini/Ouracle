"""Behavioural tests for the shared sync worker in backend.src.api.main."""

from __future__ import annotations

import asyncio

import pytest

from backend.src.api import main


class FakeAutomator:
    """Minimal stand-in for OuraAutomator's sync surface."""

    def __init__(self, *, existing_export="C:/tmp/oura-export.zip", login_result=None):
        self._is_initialized = False
        self.email = ""
        self.existing_export = existing_export
        self.login_result = login_result
        self.download_calls = 0
        self.request_calls: list[bool] = []
        self.cleanup_calls = 0

    async def initialize(self, headless=True):
        self._is_initialized = True

    async def cleanup(self):
        self.cleanup_calls += 1
        self._is_initialized = False

    async def login(self):
        return self.login_result

    async def download_existing_export(self, save_dir=None):
        self.download_calls += 1
        return self.existing_export

    async def request_new_export_and_download(
        self,
        save_dir,
        *,
        skip_ready_download=False,
        wait_for_ready=True,
    ):
        self.request_calls.append(skip_ready_download)
        return {"status": "export_requested"}


@pytest.fixture
def sync_env(monkeypatch):
    """Isolate the worker from config, activity log, and ingestion side effects."""
    state = {"status": "Idle", "is_active": True, "headless": True, "email": "me@example.test"}
    statuses: list[tuple[str, dict]] = []

    monkeypatch.setattr(main.config_manager, "get_config", lambda: dict(state))
    monkeypatch.setattr(
        main.config_manager,
        "update_status",
        lambda status, **kwargs: (statuses.append((status, kwargs)), state.update(status=status)),
    )
    monkeypatch.setattr(main.config_manager, "update_config", lambda **kwargs: state.update(kwargs))
    monkeypatch.setattr(main, "append_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "mark_waiting_for_export", lambda **kwargs: None)
    return state, statuses


def test_stale_existing_export_triggers_a_fresh_export_request(monkeypatch, sync_env):
    _state, _statuses = sync_env
    automator = FakeAutomator()
    monkeypatch.setattr(main, "automator", automator)

    async def fake_process_ingestion(_zip_path):
        return False  # ingested fine, but no newer day

    monkeypatch.setattr(main, "process_ingestion", fake_process_ingestion)

    asyncio.run(main.run_ingestion_task(force=True))

    # The ready export on Oura was already ingested, so ask for a new one and
    # do not re-download the same stale file.
    assert automator.request_calls == [True]


def test_export_with_new_days_does_not_request_another_export(monkeypatch, sync_env):
    _state, _statuses = sync_env
    automator = FakeAutomator()
    monkeypatch.setattr(main, "automator", automator)

    async def fake_process_ingestion(_zip_path):
        return True

    monkeypatch.setattr(main, "process_ingestion", fake_process_ingestion)

    asyncio.run(main.run_ingestion_task(force=True))

    assert automator.request_calls == []


def test_failed_ingest_does_not_request_another_export(monkeypatch, sync_env):
    _state, _statuses = sync_env
    automator = FakeAutomator()
    monkeypatch.setattr(main, "automator", automator)

    async def fake_process_ingestion(_zip_path):
        return None  # ingest failed and already reported itself

    monkeypatch.setattr(main, "process_ingestion", fake_process_ingestion)

    asyncio.run(main.run_ingestion_task(force=True))

    assert automator.request_calls == []


def test_repeated_otp_prompts_stop_after_bounded_retries(monkeypatch, sync_env):
    _state, statuses = sync_env
    automator = FakeAutomator(existing_export={"status": "otp_required", "code_sent": True})
    monkeypatch.setattr(main, "automator", automator)

    async def always_recovers(_otp_result, *, automator_instance):
        return True

    monkeypatch.setattr(main, "resolve_otp_or_pause", always_recovers)

    asyncio.run(main.run_ingestion_task(force=True))

    assert automator.download_calls == main.MAX_OTP_RECOVERY_ATTEMPTS + 1
    assert any(status == "Error" for status, _kwargs in statuses)
