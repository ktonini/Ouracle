"""OTP timing helpers — Oura email codes expire after ~15 minutes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import config_manager

OTP_VALID_MINUTES = 15


def mark_otp_requested() -> None:
    """Record that Oura was asked to send (or re-send) a verification email."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    config_manager.update_config(otp_requested_at=now.isoformat())


def clear_otp_request() -> None:
    config_manager.update_config(otp_requested_at=None)


def otp_status_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    """Derived OTP timing fields for API responses."""
    ts = cfg.get("otp_requested_at")
    if not ts:
        return {
            "otp_requested_at": None,
            "otp_expired": None,
            "otp_minutes_remaining": None,
        }
    try:
        requested = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_minutes = (now - requested).total_seconds() / 60.0
        expired = age_minutes >= OTP_VALID_MINUTES
        remaining = max(0, int(OTP_VALID_MINUTES - age_minutes))
        return {
            "otp_requested_at": ts,
            "otp_expired": expired,
            "otp_minutes_remaining": 0 if expired else remaining,
        }
    except (TypeError, ValueError):
        return {
            "otp_requested_at": ts,
            "otp_expired": None,
            "otp_minutes_remaining": None,
        }


def otp_prompt_message(cfg: dict[str, Any], fallback: str | None = None) -> str:
    """User-facing OTP guidance based on when the last code was requested."""
    base = fallback or "Enter the verification code sent to your email."
    fields = otp_status_fields(cfg)
    if not fields["otp_requested_at"]:
        return (
            f"{base} Oura codes expire after {OTP_VALID_MINUTES} minutes. "
            "If yours is older, send a new code below."
        )
    if fields["otp_expired"]:
        return (
            f"Your verification code has likely expired (Oura codes last {OTP_VALID_MINUTES} minutes). "
            "Send a new code below, then enter it here."
        )
    remaining = fields["otp_minutes_remaining"]
    if remaining is not None and remaining > 0:
        return f"{base} Code expires in about {remaining} minute(s)."
    return base


def enrich_automation_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge config with OTP timing fields and an updated prompt when waiting."""
    from .sync_recovery import enrich_with_sync_recovery

    cfg = enrich_with_sync_recovery(cfg)
    out = dict(cfg)
    out.update(otp_status_fields(cfg))
    if cfg.get("status") in ("otp_needed", "Waiting"):
        out["message"] = otp_prompt_message(cfg, cfg.get("message"))
    return out
