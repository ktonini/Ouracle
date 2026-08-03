"""Detect and recover automation runs stuck in a processing state."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from .config import config_manager

PROCESSING_STATUSES = frozenset({
    "Processing",
    "Starting...",
    "Initializing...",
    "Running Automation...",
    "Running Automation",
    "Downloading...",
    "Ingesting...",
    "Ingesting",
    "Submitting OTP...",
    "Starting manual run...",
    "Installing dependency (Chromium)...",
})

STUCK_AFTER = timedelta(minutes=20)


def mark_status_started() -> None:
    config_manager.update_config(
        status_started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def clear_status_started() -> None:
    config_manager.clear_config_values("status_started_at")


def recover_stuck_sync_if_needed(cfg: Dict[str, Any] | None = None) -> bool:
    """Reset a long-running Processing state so the user can sync again."""

    cfg = cfg or config_manager.get_config()
    status = cfg.get("status")
    if status not in PROCESSING_STATUSES:
        return False

    started = cfg.get("status_started_at")
    if not started:
        return False

    try:
        started_at = datetime.strptime(str(started), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False

    if datetime.now() - started_at < STUCK_AFTER:
        return False

    config_manager.update_status(
        "Idle",
        message=(
            "Previous sync timed out or was interrupted. "
            "Click Sync now to try again."
        ),
        status_started_at=None,
    )
    return True


def enrich_with_sync_recovery(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return config, recovering stuck sync first when applicable."""

    if recover_stuck_sync_if_needed(cfg):
        cfg = config_manager.get_config()
    return cfg
