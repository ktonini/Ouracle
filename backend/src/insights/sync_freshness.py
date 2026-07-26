"""Shared sync freshness read model used by desktop and Android.

Computes the latest local Oura day, the last successful ingest time, the last
export-request time, the current automation status, and the mobile sync server
state. Reads only existing config and database state - no new persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..ingestion.state import IngestOutcome

from sqlalchemy.orm import Session

from ..config import WAITING_FOR_EXPORT_STATUS, config_manager
from ..models import Activity, Readiness, Sleep, SleepSession


@dataclass
class SyncFreshness:
    latest_day: Optional[str]
    expected_latest_day: Optional[str]
    last_ingest_at: Optional[str]
    last_export_request_at: Optional[str]
    status: str
    message: Optional[str]
    mobile_server_enabled: bool
    mobile_server_status: Optional[str]
    automation_status: Optional[str]
    next_run: Optional[str]
    days_behind: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def expected_latest_day(today: Optional[date] = None) -> date:
    """Latest Oura day we reasonably expect before tonight's sleep completes."""

    today = today or date.today()
    return today - timedelta(days=1)


def data_lag_days(latest: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if latest is None:
        return None
    return max(0, (expected_latest_day(today) - latest).days)


def _latest_day(db: Session) -> Optional[date]:
    candidates = [
        db.query(Sleep.day).order_by(Sleep.day.desc()).limit(1).scalar(),
        db.query(Activity.day).order_by(Activity.day.desc()).limit(1).scalar(),
        db.query(Readiness.day).order_by(Readiness.day.desc()).limit(1).scalar(),
        db.query(SleepSession.day).order_by(SleepSession.day.desc()).limit(1).scalar(),
    ]
    valid = [d for d in candidates if d is not None]
    return max(valid) if valid else None


def ingest_advanced_data(before: Optional[date], after: Optional[date]) -> bool:
    return after is not None and (before is None or after > before)


_NO_NEW_DAYS_PHRASE = "no new days were added"


def _ingest_message_when_not_advanced(
    after_latest: Optional[date],
    *,
    success_message: str,
) -> str:
    """Message after ingest when the newest local day did not move forward."""

    lag = data_lag_days(after_latest)
    if after_latest is not None and lag is not None and lag <= 0:
        return (
            f"{success_message.rstrip('!')}! "
            "No new days in this export — local data is already up to date."
        )
    return (
        "Ingest finished but no new days were added. "
        "Request a fresh Oura export and sync again."
    )


def apply_post_ingest_outcome(
    outcome: "IngestOutcome",
    *,
    success_message: str = "Sync and ingestion complete!",
    partial_error: Optional[Exception] = None,
) -> None:
    """Update automation status from a structured ingest outcome."""

    advanced = outcome.advanced
    changed = outcome.changed
    after_latest = outcome.after_latest
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    err = partial_error or outcome.error

    if err is not None:
        message = f"Sync complete (partial: {err})"
        bump_last_run = False
    elif outcome.skipped_identical_zip:
        message = _ingest_message_when_not_advanced(
            after_latest,
            success_message=success_message,
        )
        bump_last_run = False
    elif advanced:
        message = success_message
        bump_last_run = True
    elif changed and outcome.updated > 0 and outcome.inserted == 0:
        n = outcome.updated
        message = (
            f"Updated {n} existing day(s); no new days yet. Local data refreshed."
        )
        bump_last_run = True
    elif changed:
        message = success_message
        bump_last_run = True
    else:
        message = _ingest_message_when_not_advanced(
            after_latest,
            success_message=success_message,
        )
        bump_last_run = False

    kwargs: Dict[str, Any] = {"message": message}
    if bump_last_run:
        kwargs["last_run"] = now_str
    config_manager.update_status("Idle", **kwargs)


def apply_post_ingest_result(
    before_latest: Optional[date],
    after_latest: Optional[date],
    *,
    success_message: str = "Sync and ingestion complete!",
    partial_error: Optional[Exception] = None,
) -> None:
    """Update automation status after a ZIP ingest (legacy before/after API)."""

    from ..ingestion.state import IngestOutcome

    apply_post_ingest_outcome(
        IngestOutcome(before_latest=before_latest, after_latest=after_latest),
        success_message=success_message,
        partial_error=partial_error,
    )


def apply_post_ingest_status(
    db: Session,
    before_latest: Optional[date],
    *,
    success_message: str = "Sync and ingestion complete!",
    partial_error: Optional[Exception] = None,
) -> None:
    """Update status using the DB session to read the latest day after ingest."""

    apply_post_ingest_result(
        before_latest,
        _latest_day(db),
        success_message=success_message,
        partial_error=partial_error,
    )


def _classify(latest: Optional[date], automation_status: Optional[str]) -> str:
    """Map raw state into a short status keyword for UI badges."""

    if automation_status in ("otp_needed", "Error"):
        return "blocked"
    if automation_status == WAITING_FOR_EXPORT_STATUS:
        # Waiting for a multi-day Oura export is not an active sync spinner state.
        if latest is None:
            return "empty"
        lag = data_lag_days(latest)
        if lag is None or lag <= 0:
            return "fresh"
        if lag <= 2:
            return "stale"
        return "very_stale"
    if automation_status and automation_status not in ("Idle",):
        return "syncing"
    if latest is None:
        return "empty"
    lag = data_lag_days(latest)
    if lag is None or lag <= 0:
        return "fresh"
    if lag <= 2:
        return "stale"
    return "very_stale"


def build_sync_freshness(
    db: Session,
    mobile_server_state: Any = None,
) -> SyncFreshness:
    """Build the shared sync freshness payload.

    ``mobile_server_state`` is the dataclass returned by ``mobile_server_manager``
    if the caller has it; otherwise we report only what config knows.
    """

    from datetime import datetime

    from ..scheduling import compute_next_daily_run

    cfg = config_manager.get_config()
    latest = _latest_day(db)
    expected = expected_latest_day()
    automation_status = cfg.get("status")
    last_run = cfg.get("last_run")
    schedule_time = cfg.get("schedule_time", "11:00")
    next_run = compute_next_daily_run(datetime.now(), schedule_time).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    message = cfg.get("message") if isinstance(cfg.get("message"), str) else None

    last_export_request = cfg.get("last_export_request_at") or None

    status_keyword = _classify(latest, automation_status)
    stale_no_new_days_warning = (
        message is not None
        and _NO_NEW_DAYS_PHRASE in message.lower()
    )
    if (
        message is None
        or status_keyword in ("stale", "very_stale")
        or (status_keyword == "fresh" and stale_no_new_days_warning)
    ):
        message = _default_message(status_keyword, latest, automation_status, expected)

    mobile_enabled = bool(cfg.get("mobile_sync_enabled", False))
    mobile_status = None
    if mobile_server_state is not None:
        mobile_status = getattr(mobile_server_state, "status", None)
        if getattr(mobile_server_state, "running", False) and not mobile_status:
            mobile_status = "Running"

    days_behind = data_lag_days(latest)

    return SyncFreshness(
        latest_day=latest.isoformat() if latest else None,
        expected_latest_day=expected.isoformat(),
        last_ingest_at=last_run,
        last_export_request_at=last_export_request,
        status=status_keyword,
        message=message,
        mobile_server_enabled=mobile_enabled,
        mobile_server_status=mobile_status,
        automation_status=automation_status,
        next_run=next_run,
        days_behind=days_behind,
    )


def _default_message(
    status_keyword: str,
    latest: Optional[date],
    automation_status: Optional[str],
    expected: date,
) -> str:
    if status_keyword == "blocked":
        if automation_status == "otp_needed":
            return "OTP required to continue sync."
        return "Sync is blocked. Check Settings for details."
    if status_keyword == "syncing":
        return automation_status or "Sync in progress."
    if status_keyword == "empty":
        return "No Oura data has been ingested yet."
    if latest is None:
        return "Status unknown."
    lag = data_lag_days(latest)
    if status_keyword == "fresh":
        return f"Up to date through {latest.isoformat()} (expecting through {expected.isoformat()})."
    assert lag is not None and lag > 0
    return (
        f"Latest local day is {latest.isoformat()}; "
        f"missing {lag} day(s) before expected {expected.isoformat()}."
    )
