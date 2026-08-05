"""Credential providers for the Oura API v2.

Two ways to obtain a bearer token:

- ``StaticTokenProvider``: a personal access token from ``OURACLE_OURA_TOKEN``.
- ``OAuth2RefreshProvider``: exchanges a refresh token for access tokens and
  persists rotated refresh tokens to the data dir, for when Oura sunsets PATs.

``provider_from_env()`` picks whichever the environment configures.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("OuraV2Credentials")

OAUTH_TOKEN_URL = "https://api.ouraring.com/oauth/token"

# Refresh the access token this many seconds before its reported expiry.
EXPIRY_MARGIN_SECONDS = 120


class CredentialError(Exception):
    """Credentials are missing, rejected, or unrefreshable. Not retryable."""


class StaticTokenProvider:
    """A fixed bearer token (Oura personal access token)."""

    def __init__(self, token: Optional[str] = None):
        self._token = (token or os.environ.get("OURACLE_OURA_TOKEN", "")).strip()
        if not self._token:
            raise CredentialError(
                "No Oura token configured. Set OURACLE_OURA_TOKEN."
            )

    def get_token(self) -> str:
        return self._token

    def invalidate(self) -> None:
        """A static token cannot be refreshed; a 401 means it is dead."""
        raise CredentialError(
            "Oura rejected the personal access token (401). "
            "Generate a new token and update OURACLE_OURA_TOKEN."
        )


class OAuth2RefreshProvider:
    """Maintains an access token via the OAuth2 refresh-token flow.

    Oura rotates refresh tokens on use, so the latest one is persisted to
    ``<state_dir>/oura_oauth.json``. The env var seeds the very first exchange.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        state_dir: Optional[Path] = None,
        http: Optional[httpx.Client] = None,
    ):
        self._client_id = client_id or os.environ.get("OURACLE_OURA_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get(
            "OURACLE_OURA_CLIENT_SECRET", ""
        )
        env_refresh = refresh_token or os.environ.get(
            "OURACLE_OURA_REFRESH_TOKEN", ""
        )
        if not (self._client_id and self._client_secret and env_refresh):
            raise CredentialError(
                "OAuth2 requires OURACLE_OURA_CLIENT_ID, OURACLE_OURA_CLIENT_SECRET "
                "and OURACLE_OURA_REFRESH_TOKEN."
            )

        if state_dir is None:
            from ..paths import get_user_data_dir

            state_dir = Path(get_user_data_dir())
        self._state_path = state_dir / "oura_oauth.json"
        self._http = http or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        # A previously persisted (rotated) refresh token beats the env seed.
        self._refresh_token = self._load_persisted_refresh() or env_refresh

    def _load_persisted_refresh(self) -> Optional[str]:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                return json.load(f).get("refresh_token") or None
        except (OSError, ValueError):
            return None

    def _persist_refresh(self, refresh_token: str) -> None:
        try:
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"refresh_token": refresh_token}), encoding="utf-8"
            )
            os.replace(tmp, self._state_path)
        except OSError as e:
            logger.warning("Could not persist rotated refresh token: %s", e)

    def _refresh(self) -> None:
        response = self._http.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if response.status_code in (400, 401):
            raise CredentialError(
                f"Oura refused the refresh token ({response.status_code}): "
                f"{response.text[:200]}. Re-authorize the application."
            )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + float(payload.get("expires_in", 86400))
        rotated = payload.get("refresh_token")
        if rotated and rotated != self._refresh_token:
            self._refresh_token = rotated
            self._persist_refresh(rotated)

    def get_token(self) -> str:
        with self._lock:
            if (
                self._access_token is None
                or time.time() >= self._expires_at - EXPIRY_MARGIN_SECONDS
            ):
                self._refresh()
            assert self._access_token is not None
            return self._access_token

    def invalidate(self) -> None:
        """Force a refresh on next use (e.g. after a 401 mid-flight)."""
        with self._lock:
            self._access_token = None


def provider_from_env():
    """OAuth2 when a refresh token is configured, otherwise a static PAT."""
    if os.environ.get("OURACLE_OURA_REFRESH_TOKEN"):
        return OAuth2RefreshProvider()
    return StaticTokenProvider()
