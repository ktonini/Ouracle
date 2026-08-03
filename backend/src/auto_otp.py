"""Deterministic automatic OTP retrieval from local Thunderbird/Betterbird mail."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .betterbird import BetterbirdUnavailable, ensure_betterbird_running, is_betterbird_running
from .thunderbird_otp import DEFAULT_CODE_PATTERN, FoundOtp, find_fresh_otp


REQUEST_TIME_SKEW_SECONDS = 30
LIVE_RPC_TIMEOUT_MARGIN_SECONDS = 10
BETTERBIRD_RPC_RETRY_SECONDS = 1


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

    accounts = _expect_records(_ensure_betterbird_ready(config, base_url), "listAccounts")
    account_ids = {
        account.get("id")
        for account in accounts
        if any(str(identity.get("email", "")).casefold() == account_email for identity in account.get("identities", []))
    }
    if not account_ids:
        raise LiveMailboxUnavailable("Configured Oura mailbox is not available in Betterbird")

    folders = _expect_records(
        _rpc(base_url, "listFolders", {}, timeout_seconds=15),
        "listFolders",
    )
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
    if not isinstance(result, dict):
        raise LiveMailboxUnavailable("Betterbird bridge returned an unexpected waitForMessage result")
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


def _expect_records(value: Any, method: str) -> list[dict[str, Any]]:
    """Treat an unexpected bridge payload as 'bridge unavailable', not a crash.

    The mailbox bridge is an optional external add-on, so a malformed reply
    must fall back to the read-only mbox reader like any other failure.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise LiveMailboxUnavailable(f"Betterbird bridge returned an unexpected {method} result")
    return value


def _ensure_betterbird_ready(config: dict[str, Any], base_url: str) -> Any:
    """Start Betterbird if needed and wait for its local bridge to initialize."""
    if not bool(config.get("auto_otp_betterbird_launch_enabled", True)):
        if not is_betterbird_running():
            raise LiveMailboxUnavailable("Betterbird launch is disabled and it is not running")
    else:
        try:
            ensure_betterbird_running(config)
        except BetterbirdUnavailable as exc:
            raise LiveMailboxUnavailable(str(exc)) from exc

    wait_seconds = max(
        0,
        int(config.get("auto_otp_betterbird_startup_wait_seconds", 60)),
    )
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while True:
        try:
            return _rpc(base_url, "listAccounts", {}, timeout_seconds=3)
        except LiveMailboxUnavailable as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            detail = f": {last_error}" if last_error else ""
            raise LiveMailboxUnavailable(
                "Betterbird mailbox bridge did not become ready within "
                f"{wait_seconds} seconds{detail}"
            )
        time.sleep(min(BETTERBIRD_RPC_RETRY_SECONDS, max(0, deadline - time.monotonic())))


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
