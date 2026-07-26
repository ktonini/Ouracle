"""Durable waiting state while Oura generates a multi-day export."""

from __future__ import annotations

from datetime import datetime

from .activity_log import append_activity
from .config import WAITING_FOR_EXPORT_STATUS, config_manager


def mark_waiting_for_export(*, requested_now: bool) -> None:
    requested_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if requested_now:
        config_manager.update_config(last_export_request_at=requested_at)
        append_activity(
            "Export requested from Oura — waiting for generation (can take days).",
            category="export",
        )
    else:
        cfg = config_manager.get_config()
        requested_at = cfg.get("last_export_request_at") or requested_at
    message = (
        f"Oura is generating an export (requested {requested_at}). "
        "This can take days. The app will keep checking while it is running, "
        "including after restart."
    )
    config_manager.update_status(
        WAITING_FOR_EXPORT_STATUS,
        message=message,
        logged_in=True,
    )
