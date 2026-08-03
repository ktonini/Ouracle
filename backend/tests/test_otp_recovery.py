from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from backend.src import otp_recovery
from backend.src.thunderbird_otp import FoundOtp


class FakeAutomator:
    def __init__(self):
        self.submitted: list[str] = []

    async def submit_otp(self, code: str):
        self.submitted.append(code)
        return {"status": "success", "message": "Login successful"}


def test_resolver_submits_fresh_local_code(monkeypatch):
    state = {"auto_otp_enabled": True, "status": "otp_needed"}
    statuses = []
    automator = FakeAutomator()
    found = FoundOtp(
        code="757458",
        message_date=datetime.now(timezone.utc),
        source_path=Path("INBOX"),
        sender="Oura <support@ouraring.com>",
        subject="One time password",
    )

    monkeypatch.setattr(otp_recovery.config_manager, "get_config", lambda: dict(state))
    monkeypatch.setattr(
        otp_recovery.config_manager,
        "update_status",
        lambda status, **kwargs: (
            statuses.append((status, kwargs)),
            state.update(status=status, **kwargs),
        ),
    )
    monkeypatch.setattr(
        otp_recovery.config_manager,
        "update_config",
        lambda **kwargs: state.update(kwargs),
    )
    monkeypatch.setattr(otp_recovery, "mark_otp_requested", lambda: None)
    monkeypatch.setattr(otp_recovery, "clear_otp_request", lambda: None)
    monkeypatch.setattr(otp_recovery, "append_activity", lambda *args, **kwargs: None)

    async def fake_wait(_config):
        return found

    monkeypatch.setattr(otp_recovery, "wait_for_configured_otp", fake_wait)

    resolved = asyncio.run(
        otp_recovery.resolve_otp_or_pause(
            {"status": "otp_required", "code_sent": True},
            automator_instance=automator,
        )
    )

    assert resolved is True
    assert automator.submitted == ["757458"]
    assert any(status == "Submitting OTP…" for status, _kwargs in statuses)


def test_resolver_requests_a_code_when_upstream_did_not_send_one(monkeypatch):
    state = {"auto_otp_enabled": True, "status": "otp_needed"}
    resend_calls = []

    class ResendAutomator(FakeAutomator):
        async def resend_otp(self):
            resend_calls.append(True)
            return {"status": "otp_required", "code_sent": True}

    monkeypatch.setattr(otp_recovery.config_manager, "get_config", lambda: dict(state))
    monkeypatch.setattr(
        otp_recovery.config_manager,
        "update_status",
        lambda status, **kwargs: state.update(status=status, **kwargs),
    )
    monkeypatch.setattr(
        otp_recovery.config_manager,
        "update_config",
        lambda **kwargs: state.update(kwargs),
    )
    monkeypatch.setattr(otp_recovery, "mark_otp_requested", lambda: None)
    monkeypatch.setattr(otp_recovery, "append_activity", lambda *args, **kwargs: None)

    async def fake_wait(_config):
        return None

    monkeypatch.setattr(otp_recovery, "wait_for_configured_otp", fake_wait)

    resolved = asyncio.run(
        otp_recovery.resolve_otp_or_pause(
            {"status": "otp_required", "code_sent": False},
            automator_instance=ResendAutomator(),
        )
    )

    assert resolved is False
    assert resend_calls == [True]
