"""Push notifications via Pushover.

Reads OURACLE_PUSHOVER_TOKEN / OURACLE_PUSHOVER_USER from the environment;
silently no-ops when unconfigured so callers don't need to care.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("Notify")

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def pushover_configured() -> bool:
    return bool(
        os.environ.get("OURACLE_PUSHOVER_TOKEN")
        and os.environ.get("OURACLE_PUSHOVER_USER")
    )


def send_pushover(message: str, title: str = "Ouracle") -> bool:
    """Send a notification; returns True on success."""
    token = os.environ.get("OURACLE_PUSHOVER_TOKEN", "")
    user = os.environ.get("OURACLE_PUSHOVER_USER", "")
    if not token or not user:
        logger.info("Pushover not configured; skipping notification: %s", message)
        return False
    try:
        response = httpx.post(
            PUSHOVER_URL,
            data={"token": token, "user": user, "title": title, "message": message},
            timeout=15.0,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as e:
        logger.error("Pushover send failed: %s", e)
        return False
