"""Paginating HTTP client for the Oura API v2.

Handles bearer auth, ``next_token`` pagination, retry with backoff on 429/5xx,
and a hard failure on 401 so a dead credential is loud instead of a silently
stale database. ``OURACLE_OURA_SANDBOX=1`` targets the sandbox mirror, which
accepts any token — useful for development without real credentials.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterator, Optional, Union

import httpx

from .credentials import CredentialError

logger = logging.getLogger("OuraV2Client")

API_BASE = "https://api.ouraring.com"
LIVE_PREFIX = "/v2/usercollection"
SANDBOX_PREFIX = "/v2/sandbox/usercollection"

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0


class OuraApiError(Exception):
    """Non-auth API failure that survived retries."""


class OuraV2Client:
    def __init__(
        self,
        credentials,
        sandbox: Optional[bool] = None,
        http: Optional[httpx.Client] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._credentials = credentials
        if sandbox is None:
            sandbox = os.environ.get("OURACLE_OURA_SANDBOX", "") in ("1", "true")
        self._prefix = SANDBOX_PREFIX if sandbox else LIVE_PREFIX
        self._http = http or httpx.Client(base_url=API_BASE, timeout=60.0)
        self._sleep = sleep_fn

    def fetch_collection(
        self,
        collection: str,
        start: Optional[Union[date, datetime]] = None,
        end: Optional[Union[date, datetime]] = None,
        datetime_params: bool = False,
    ) -> Iterator[Dict[str, Any]]:
        """Yield every document in a collection across all pages.

        ``datetime_params`` selects ``start_datetime``/``end_datetime`` (used by
        the heartrate and ring_battery_level time-series endpoints) instead of
        ``start_date``/``end_date``.
        """
        params: Dict[str, str] = {}
        prefix = "start_datetime" if datetime_params else "start_date"
        suffix = "end_datetime" if datetime_params else "end_date"
        if start is not None:
            params[prefix] = start.isoformat()
        if end is not None:
            params[suffix] = end.isoformat()

        next_token: Optional[str] = None
        while True:
            if next_token:
                params["next_token"] = next_token
            payload = self._get(f"{self._prefix}/{collection}", params)
            for doc in payload.get("data", []):
                yield doc
            next_token = payload.get("next_token")
            if not next_token:
                return

    def fetch_single(self, collection: str) -> Dict[str, Any]:
        """Fetch a single-document endpoint (e.g. personal_info)."""
        return self._get(f"/v2/usercollection/{collection}", {})

    def _get(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        retried_auth = False
        for attempt in range(MAX_RETRIES):
            response = self._http.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {self._credentials.get_token()}"},
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code == 401:
                # Give refreshable credentials one second chance; a static
                # token raises CredentialError from invalidate() immediately.
                self._credentials.invalidate()
                if retried_auth:
                    raise CredentialError(
                        f"Oura still returns 401 after token refresh on {path}."
                    )
                retried_auth = True
                continue

            if response.status_code in (403,):
                raise CredentialError(
                    f"Oura returned 403 for {path} — token lacks the required "
                    f"scope or the subscription does not expose this data."
                )

            if response.status_code == 429 or response.status_code >= 500:
                delay = float(
                    response.headers.get(
                        "Retry-After", BACKOFF_BASE_SECONDS * (2**attempt)
                    )
                )
                logger.warning(
                    "Oura %s on %s (attempt %d/%d), retrying in %.1fs",
                    response.status_code,
                    path,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                self._sleep(delay)
                continue

            raise OuraApiError(
                f"Oura API {response.status_code} on {path}: {response.text[:300]}"
            )

        raise OuraApiError(f"Oura API retries exhausted on {path}.")
