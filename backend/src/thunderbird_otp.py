"""Read fresh one-time passwords from Thunderbird/Betterbird's local mbox cache.

This is deliberately local and deterministic: it never sends mail, talks to a
cloud provider, or marks a message read.  It supports Thunderbird and
Betterbird because both use Thunderbird profiles and (by default) mbox files
for IMAP folders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import os
from pathlib import Path
import re
from typing import Iterable


DEFAULT_CODE_PATTERN = r"(?:one\s*time\s*password|verification\s*code)\D{0,80}\b(\d{6})\b"
DEFAULT_TAIL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class FoundOtp:
    code: str
    message_date: datetime
    source_path: Path
    sender: str
    subject: str


def default_profile_roots() -> list[Path]:
    """Return conventional Thunderbird/Betterbird profile directories."""
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.extend(
            [
                Path(appdata) / "Thunderbird" / "Profiles",
                Path(appdata) / "Betterbird" / "Profiles",
            ]
        )
    home = Path.home()
    roots.extend(
        [
            home / ".thunderbird",
            home / ".betterbird",
            home / "Library" / "Thunderbird" / "Profiles",
            home / "Library" / "Betterbird" / "Profiles",
        ]
    )
    return [root for root in roots if root.exists()]


def find_fresh_otp(
    *,
    after: datetime,
    sender: str,
    subject: str,
    profile_root: Path | None = None,
    code_pattern: str = DEFAULT_CODE_PATTERN,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> FoundOtp | None:
    """Return the latest matching OTP received strictly after ``after``.

    Only Inbox mbox files are read.  The final part of each file is enough for
    newly received mail while avoiding a full scan of multi-gigabyte caches.
    """
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    else:
        after = after.astimezone(timezone.utc)

    roots = [profile_root] if profile_root is not None else default_profile_roots()
    pattern = re.compile(code_pattern, re.IGNORECASE | re.DOTALL)
    matches: list[FoundOtp] = []
    for inbox in _iter_inboxes(roots):
        try:
            payload = _read_tail(inbox, tail_bytes)
        except OSError:
            continue
        matches.extend(_matching_messages(payload, inbox, after, sender, subject, pattern))

    return max(matches, key=lambda item: item.message_date) if matches else None


def _iter_inboxes(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root or not root.exists():
            continue
        try:
            for candidate in root.rglob("*"):
                if candidate.is_file() and candidate.name.casefold() == "inbox":
                    parts = {part.casefold() for part in candidate.parts}
                    if "imapmail" in parts or "mail" in parts:
                        yield candidate
        except OSError:
            continue


def _read_tail(path: Path, tail_bytes: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        return handle.read()


def _matching_messages(
    payload: bytes,
    source_path: Path,
    after: datetime,
    sender: str,
    subject: str,
    code_pattern: re.Pattern[str],
) -> Iterable[FoundOtp]:
    # mbox message separators begin at a physical line with "From "; regular
    # From headers include a colon and therefore do not match.
    boundaries = [match.start() for match in re.finditer(br"(?m)^From .*$", payload)]
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(payload)
        raw_message = payload[start:end]
        header_end = raw_message.find(b"\n")
        if header_end < 0:
            continue
        try:
            message = BytesParser(policy=policy.default).parsebytes(raw_message[header_end + 1 :])
        except (UnicodeError, ValueError):
            continue
        message_date = _message_date(message.get("Date"))
        if message_date is None or message_date <= after:
            continue
        message_sender = str(message.get("From", ""))
        message_subject = str(message.get("Subject", ""))
        if sender.casefold() not in message_sender.casefold():
            continue
        if subject.casefold() not in message_subject.casefold():
            continue
        code_match = code_pattern.search(raw_message.decode("utf-8", errors="replace"))
        if not code_match:
            continue
        yield FoundOtp(
            code=code_match.group(1),
            message_date=message_date,
            source_path=source_path,
            sender=message_sender,
            subject=message_subject,
        )


def _message_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
