"""Shared orchestration for automatic and manual Oura OTP recovery."""

from __future__ import annotations

from typing import Any

from .activity_log import append_activity
from .auto_otp import auto_otp_enabled, wait_for_configured_otp
from .config import config_manager
from .otp_state import clear_otp_request, mark_otp_requested, otp_prompt_message


# Automatic recovery re-runs the interrupted operation after signing in. Bound
# those retries so a session that keeps landing back on the OTP screen cannot
# recurse forever (and cannot keep asking Oura for new codes).
MAX_OTP_RECOVERY_ATTEMPTS = 2


async def resolve_otp_or_pause(
    otp_result: dict[str, Any],
    *,
    automator_instance: Any,
) -> bool:
    """Submit a fresh local OTP when enabled, otherwise leave manual UI active.

    ``True`` means the active browser session is authenticated and the caller
    may retry its interrupted operation. ``False`` means the caller should
    stop and leave the ordinary OTP prompt available to the user.
    """
    code_sent = bool(otp_result.get("code_sent"))
    if code_sent:
        mark_otp_requested()

    cfg = config_manager.get_config()
    if auto_otp_enabled(cfg):
        # If the upstream flow did not send a code, request one before waiting
        # in the mailbox. Callers must preserve ``code_sent`` when propagating
        # an OTP result so this resend is not performed unnecessarily.
        if not code_sent:
            resend_result = await automator_instance.resend_otp()
            if resend_result.get("status") == "otp_required" and resend_result.get(
                "code_sent"
            ):
                mark_otp_requested()
            else:
                # Keep the mailbox fallback useful even if Oura's resend
                # control was unavailable on the current page.
                append_activity(
                    "Could not confirm a fresh Oura code request; checking local mail…",
                    level="warning",
                    category="auth",
                )

        config_manager.update_status(
            "otp_needed",
            message="Waiting for a fresh verification code in Thunderbird/Betterbird…",
        )
        found = await wait_for_configured_otp(config_manager.get_config())
        if found is not None:
            # Never log the OTP itself.
            append_activity(
                "Found verification code in local mail — submitting…",
                category="auth",
            )
            config_manager.update_status(
                "Submitting OTP…",
                message="Submitting verification code…",
            )
            submitted = await automator_instance.submit_otp(found.code)
            if submitted.get("status") == "success":
                clear_otp_request()
                config_manager.update_config(logged_in=True)
                append_activity(
                    "Signed in to Oura successfully.",
                    level="success",
                    category="auth",
                )
                return True
            config_manager.update_status(
                "otp_needed",
                message=submitted.get("message", "OTP submission failed."),
            )
            return False

        cfg = config_manager.get_config()
        config_manager.update_status(
            "otp_needed",
            message=(
                "No matching fresh verification email appeared in the local "
                "Thunderbird/Betterbird cache. "
                + otp_prompt_message(cfg, "Enter the verification code manually.")
            ),
        )
        return False

    cfg = config_manager.get_config()
    config_manager.update_status(
        "otp_needed",
        message=otp_prompt_message(cfg, "Check your email for a verification code."),
    )
    return False
