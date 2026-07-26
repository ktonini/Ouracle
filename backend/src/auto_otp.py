"""Deterministic automatic OTP retrieval from local Thunderbird/Betterbird mail."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .thunderbird_otp import DEFAULT_CODE_PATTERN, FoundOtp, find_fresh_otp


REQUEST_TIME_SKEW_SECONDS = 30
LIVE_RPC_TIMEOUT_MARGIN_SECONDS = 10


class LiveMailboxUnavailable(RuntimeError):
    """The optional Betterbird live bridge cannot currently answer requests."""


def auto_otp_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("auto_otp_enabled", False))


async def wait_for_configured_otp(config: dict[str, Any]) -> FoundOtp | None:
    """Wait for a fresh OTP, preferring Betterbird's live API over mbox cache.

    A live API timeout is authoritative: Thunderbird was queried directly and
    did not have a matching message. A bridge/network failure falls back to the
    read-only local mbox cache so standalone Thunderbird still works.
    """
    if not auto_otp_enabled(config):
        return None

    if config.get("auto_otp_live_mailbox_enabled", True):
        try:
            live_result = await asyncio.to_thread(_wait_for_live_mailbox_otp, config)
            return live_result
        except LiveMailboxUnavailable:
            # Betterbird is optional. Continue with the standard Thunderbird
            # mbox cache instead of making a live API dependency mandatory.
            pass

    return await _wait_for_mbox_otp(config)


async def _wait_for_mbox_otp(config: dict[str, Any]) -> FoundOtp | None:
    requested_at = _requested_at(config)
    timeout_seconds = max(1, int(config.get("auto_otp_timeout_seconds", 120)))
    poll_seconds = max(1, int(config.get("auto_otp_poll_seconds", 3)))
    profile_root_value = str(config.get("auto_otp_profile_root", "")).strip()
    profile_root = Path(profile_root_value).expanduser() if profile_root_value else None
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while True:
        found = await asyncio.to_thread(
            find_fresh_otp,
            after=requested_at,
            sender=str(config.get("auto_otp_sender", "support@ouraring.com")),
            subject=str(config.get("auto_otp_subject", "One time password")),
            profile_root=profile_root,
            code_pattern=str(config.get("auto_otp_code_pattern", DEFAULT_CODE_PATTERN)),
        )
        if found is not None:
            return found
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(poll_seconds)


def _wait_for_live_mailbox_otp(config: dict[str, Any]) -> FoundOtp | None:
    base_url = str(config.get("auto_otp_mailbox_api_url", "http://127.0.0.1:8766")).rstrip("/")
    after = _requested_at(config)
    timeout_seconds = max(1, int(config.get("auto_otp_timeout_seconds", 120)))
    sender = str(config.get("auto_otp_sender", "support@ouraring.com"))
    subject = str(config.get("auto_otp_subject", "One time password"))
    account_email = str(config.get("email", "")).casefold()

    accounts = _rpc(base_url, "listAccounts", {}, timeout_seconds=15)
    account_ids = {
        account.get("id")
        for account in accounts
        if any(str(identity.get("email", "")).casefold() == account_email for identity in account.get("identities", []))
    }
    if not account_ids:
        raise LiveMailboxUnavailable("Configured Oura mailbox is not available in Betterbird")

    folders = _rpc(base_url, "listFolders", {}, timeout_seconds=15)
    folder_ids = [
        folder.get("id")
        for folder in folders
        if folder.get("accountId") in account_ids and str(folder.get("type", "")).casefold() == "inbox"
    ]
    if not folder_ids:
        raise LiveMailboxUnavailable("Configured Betterbird account has no Inbox folder")

    result = _rpc(
        base_url,
        "waitForMessage",
        {
            "folderIds": folder_ids,
            "senderRegex": re.escape(sender),
            "subjectRegex": re.escape(subject),
            "after": after.isoformat(),
            "timeoutMs": timeout_seconds * 1000,
            "pollIntervalMs": max(250, int(config.get("auto_otp_poll_seconds", 3)) * 1000),
        },
        timeout_seconds=min(130, timeout_seconds + LIVE_RPC_TIMEOUT_MARGIN_SECONDS),
    )
    if not result.get("found"):
        return None

    message = result.get("message") or {}
    body = str(message.get("body_text", ""))
    code_match = re.search(str(config.get("auto_otp_code_pattern", DEFAULT_CODE_PATTERN)), body, re.IGNORECASE | re.DOTALL)
    if not code_match:
        return None
    message_date = _coerce_message_date(message.get("date"))
    if message_date is None or message_date <= after:
        return None
    return FoundOtp(
        code=code_match.group(1),
        message_date=message_date,
        source_path=Path("live-betterbird-rpc"),
        sender=str(message.get("author", "")),
        subject=str(message.get("subject", "")),
    )


def _rpc(base_url: str, method: str, params: dict[str, Any], *, timeout_seconds: int) -> Any:
    payload = json.dumps({"method": method, "params": params, "timeoutSeconds": timeout_seconds}).encode("utf-8")
    request = Request(
        f"{base_url}/rpc",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds + 5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError) as exc:
        raise LiveMailboxUnavailable(str(exc)) from exc
    if not body.get("ok"):
        raise LiveMailboxUnavailable(str(body.get("error", "Betterbird bridge failed")))
    return body.get("result")


def _requested_at(config: dict[str, Any]) -> datetime:
    value = config.get("otp_requested_at")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc) - timedelta(seconds=REQUEST_TIME_SKEW_SECONDS)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc) - timedelta(seconds=REQUEST_TIME_SKEW_SECONDS)


def _coerce_message_date(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
