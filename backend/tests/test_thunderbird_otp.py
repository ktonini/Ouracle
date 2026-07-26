from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from backend.src.thunderbird_otp import find_fresh_otp


def _append_message(
    inbox: Path,
    *,
    when: datetime,
    sender: str = "Oura <support@ouraring.com>",
    subject: str = "One time password",
    body: str = "One time password: 123456",
) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(
        "From sender@example.com " + when.strftime("%a %b %d %H:%M:%S %Y") + "\n"
        f"Date: {format_datetime(when)}\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_find_fresh_otp_reads_matching_thunderbird_mbox(tmp_path: Path):
    after = datetime(2026, 7, 12, 9, 15, tzinfo=timezone.utc)
    inbox = tmp_path / "Profiles" / "profile.default" / "ImapMail" / "imap.example.test" / "INBOX"
    _append_message(inbox, when=after + timedelta(seconds=10), body="Login\nOne time password: 757458")

    found = find_fresh_otp(
        profile_root=tmp_path / "Profiles",
        after=after,
        sender="support@ouraring.com",
        subject="One time password",
    )

    assert found is not None
    assert found.code == "757458"
    assert found.message_date == after + timedelta(seconds=10)
    assert found.source_path == inbox


def test_find_fresh_otp_rejects_old_or_wrong_sender_messages(tmp_path: Path):
    after = datetime(2026, 7, 12, 9, 15, tzinfo=timezone.utc)
    inbox = tmp_path / "Profiles" / "profile.default" / "ImapMail" / "imap.example.test" / "INBOX"
    _append_message(inbox, when=after - timedelta(minutes=1), body="One time password: 111111")
    with inbox.open("a", encoding="utf-8") as f:
        f.write(
            "From sender@example.com Sun Jul 12 09:15:10 2026\n"
            f"Date: {format_datetime(after + timedelta(seconds=10))}\n"
            "From: attacker@example.test\n"
            "Subject: One time password\n\n"
            "One time password: 999999\n"
        )

    assert find_fresh_otp(
        profile_root=tmp_path / "Profiles",
        after=after,
        sender="support@ouraring.com",
        subject="One time password",
    ) is None
