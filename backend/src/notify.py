"""Push notifications: native APNs to registered devices, Pushover fallback.

APNs env: OURACLE_APNS_KEY (path to the .p8), OURACLE_APNS_KEY_ID,
OURACLE_APNS_TEAM_ID, optional OURACLE_APNS_TOPIC (defaults to the app's
bundle id). Device tokens are registered by the iOS app via
POST /api/mobile/push-token and stored in ingest_state.

Pushover env: OURACLE_PUSHOVER_TOKEN / OURACLE_PUSHOVER_USER.
Both senders silently no-op when unconfigured.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("Notify")

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
APNS_HOST = "https://api.push.apple.com"
APNS_DEFAULT_TOPIC = "com.ktonini.ouracle"
DEVICE_TOKEN_PREFIX = "apns_device:"


class ApnsSender:
    """Token-authenticated APNs over HTTP/2. JWTs are cached ~50 minutes
    (Apple requires 20-60 min token lifetimes)."""

    def __init__(self, http: Optional[httpx.Client] = None):
        self.key_path = os.environ.get("OURACLE_APNS_KEY", "")
        self.key_id = os.environ.get("OURACLE_APNS_KEY_ID", "")
        self.team_id = os.environ.get("OURACLE_APNS_TEAM_ID", "")
        self.topic = os.environ.get("OURACLE_APNS_TOPIC", APNS_DEFAULT_TOPIC)
        self._http = http or httpx.Client(base_url=APNS_HOST, http2=True, timeout=15.0)
        self._jwt: Optional[str] = None
        self._jwt_issued = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.key_path and self.key_id and self.team_id)

    def _token(self) -> str:
        import jwt

        if self._jwt is None or time.time() - self._jwt_issued > 3000:
            with open(self.key_path) as f:
                key = f.read()
            self._jwt = jwt.encode(
                {"iss": self.team_id, "iat": int(time.time())},
                key,
                algorithm="ES256",
                headers={"kid": self.key_id},
            )
            self._jwt_issued = time.time()
        return self._jwt

    def send(self, device_token: str, title: str, body: str) -> str:
        """Returns 'ok', 'unregistered' (token dead — caller should drop it),
        or 'error'."""
        payload = {
            "aps": {
                "alert": {"title": title, "body": body},
                "sound": "default",
            }
        }
        try:
            response = self._http.post(
                f"/3/device/{device_token}",
                content=json.dumps(payload),
                headers={
                    "authorization": f"bearer {self._token()}",
                    "apns-topic": self.topic,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                },
            )
        except httpx.HTTPError as e:
            logger.error("APNs send failed: %s", e)
            return "error"
        if response.status_code == 200:
            return "ok"
        if response.status_code == 410:
            return "unregistered"
        logger.error(
            "APNs %s for %s…: %s",
            response.status_code,
            device_token[:8],
            response.text[:200],
        )
        return "error"


def registered_device_tokens(db) -> Dict[str, str]:
    """token -> device name, from ingest_state."""
    from .models import IngestState

    rows = (
        db.query(IngestState)
        .filter(IngestState.key.like(DEVICE_TOKEN_PREFIX + "%"))
        .all()
    )
    return {row.key[len(DEVICE_TOKEN_PREFIX):]: row.value or "" for row in rows}


def notify(db, title: str, message: str, apns: Optional[ApnsSender] = None) -> bool:
    """Native push to every registered device; Pushover only as fallback
    when APNs is unconfigured or reaches nobody."""
    from .models import IngestState

    apns = apns or ApnsSender()
    delivered = False
    if apns.configured:
        for token, name in registered_device_tokens(db).items():
            result = apns.send(token, title, message)
            if result == "ok":
                delivered = True
            elif result == "unregistered":
                logger.info("Dropping dead APNs token for %r", name)
                row = db.get(IngestState, DEVICE_TOKEN_PREFIX + token)
                if row is not None:
                    db.delete(row)
                    db.commit()
    if not delivered:
        delivered = send_pushover(message, title=title)
    return delivered


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
