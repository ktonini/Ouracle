"""Oura v2 client: pagination, retry, and credential failure behavior."""

import httpx
import pytest

from backend.src.oura_v2.client import OuraApiError, OuraV2Client
from backend.src.oura_v2.credentials import CredentialError, StaticTokenProvider


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.ouraring.com")
    return OuraV2Client(
        StaticTokenProvider("test-pat"),
        sandbox=False,
        http=http,
        sleep_fn=lambda s: None,
        **kwargs,
    )


def test_pagination_follows_next_token():
    pages = {
        None: {"data": [{"id": "a"}, {"id": "b"}], "next_token": "t2"},
        "t2": {"data": [{"id": "c"}], "next_token": None},
    }
    seen_tokens = []

    def handler(request):
        token = request.url.params.get("next_token")
        seen_tokens.append(token)
        return httpx.Response(200, json=pages[token])

    client = make_client(handler)
    docs = list(client.fetch_collection("daily_sleep"))
    assert [d["id"] for d in docs] == ["a", "b", "c"]
    assert seen_tokens == [None, "t2"]


def test_bearer_header_and_date_params():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": []})

    from datetime import date

    client = make_client(handler)
    list(client.fetch_collection("workout", date(2026, 8, 1), date(2026, 8, 4)))
    assert captured["auth"] == "Bearer test-pat"
    assert captured["params"]["start_date"] == "2026-08-01"
    assert captured["params"]["end_date"] == "2026-08-04"


def test_401_with_static_token_raises_credential_error():
    def handler(request):
        return httpx.Response(401, json={"detail": "invalid"})

    client = make_client(handler)
    with pytest.raises(CredentialError):
        list(client.fetch_collection("daily_sleep"))


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": [{"id": "ok"}]})

    client = make_client(handler)
    docs = list(client.fetch_collection("daily_sleep"))
    assert [d["id"] for d in docs] == ["ok"]
    assert calls["n"] == 3


def test_server_errors_exhaust_retries():
    def handler(request):
        return httpx.Response(503)

    client = make_client(handler)
    with pytest.raises(OuraApiError, match="retries exhausted"):
        list(client.fetch_collection("daily_sleep"))


def test_4xx_other_than_auth_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(422, json={"detail": "bad params"})

    client = make_client(handler)
    with pytest.raises(OuraApiError, match="422"):
        list(client.fetch_collection("daily_sleep"))
    assert calls["n"] == 1
