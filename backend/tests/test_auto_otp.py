from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.src import auto_otp
from backend.src.thunderbird_otp import FoundOtp


@pytest.mark.parametrize("enabled", [False, True])
def test_auto_otp_enabled(enabled):
    assert auto_otp.auto_otp_enabled({"auto_otp_enabled": enabled}) is enabled


def test_wait_for_configured_otp_uses_matching_fresh_code(monkeypatch, tmp_path: Path):
    requested_at = "2026-07-12T09:15:00+00:00"
    expected = FoundOtp(
        code="757458",
        message_date=datetime(2026, 7, 12, 9, 15, 10, tzinfo=timezone.utc),
        source_path=tmp_path / "INBOX",
        sender="Oura <support@ouraring.com>",
        subject="One time password",
    )
    received = {}

    def fake_find(**kwargs):
        received.update(kwargs)
        return expected

    monkeypatch.setattr(auto_otp, "find_fresh_otp", fake_find)
    found = asyncio.run(
        auto_otp.wait_for_configured_otp(
            {
                "auto_otp_enabled": True,
                "auto_otp_live_mailbox_enabled": False,
                "otp_requested_at": requested_at,
                "auto_otp_profile_root": str(tmp_path),
                "auto_otp_timeout_seconds": 1,
                "auto_otp_poll_seconds": 1,
            }
        )
    )

    assert found == expected
    assert received["sender"] == "support@ouraring.com"
    assert received["after"] == datetime(2026, 7, 12, 9, 14, 30, tzinfo=timezone.utc)


def test_live_mailbox_otp_uses_current_betterbird_message(monkeypatch):
    calls = []

    def fake_rpc(_url, method, params, *, timeout_seconds):
        calls.append((method, params, timeout_seconds))
        if method == "listAccounts":
            return [{"id": "account1", "identities": [{"email": "me@example.test"}]}]
        if method == "listFolders":
            return [{"id": "account1://INBOX", "accountId": "account1", "type": "inbox"}]
        assert method == "waitForMessage"
        return {
            "found": True,
            "message": {
                "author": "Oura <support@ouraring.com>",
                "subject": "One time password",
                "date": "2026-07-12T09:15:10+00:00",
                "body_text": "One time password: 757458",
            },
        }

    monkeypatch.setattr(auto_otp, "_rpc", fake_rpc)
    found = auto_otp._wait_for_live_mailbox_otp(
        {
            "email": "me@example.test",
            "otp_requested_at": "2026-07-12T09:15:00+00:00",
            "auto_otp_timeout_seconds": 120,
        }
    )

    assert found is not None
    assert found.code == "757458"
    wait_call = next(call for call in calls if call[0] == "waitForMessage")
    assert wait_call[1]["folderIds"] == ["account1://INBOX"]
    assert wait_call[1]["after"] == "2026-07-12T09:14:30+00:00"
    assert wait_call[2] == 130


def test_wait_for_configured_otp_is_disabled_without_opt_in(monkeypatch):
    monkeypatch.setattr(auto_otp, "find_fresh_otp", lambda **kwargs: pytest.fail("must not read mail"))
    assert asyncio.run(auto_otp.wait_for_configured_otp({"auto_otp_enabled": False})) is None
