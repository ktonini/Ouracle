"""APNs sender, token registry, and fallback routing."""

import json
from datetime import date

import httpx
import pytest

from backend.src import notify
from backend.src.models import IngestState


@pytest.fixture
def apns_env(monkeypatch, tmp_path):
    # Throwaway EC P-256 key so JWT signing is real.
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_path = tmp_path / "apns.p8"
    key_path.write_bytes(pem)
    monkeypatch.setenv("OURACLE_APNS_KEY", str(key_path))
    monkeypatch.setenv("OURACLE_APNS_KEY_ID", "TESTKEY123")
    monkeypatch.setenv("OURACLE_APNS_TEAM_ID", "K3M2778TQN")
    monkeypatch.delenv("OURACLE_PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("OURACLE_PUSHOVER_USER", raising=False)


def make_sender(handler):
    transport = httpx.MockTransport(handler)
    return notify.ApnsSender(
        http=httpx.Client(transport=transport, base_url=notify.APNS_HOST)
    )


def test_send_sets_headers_and_payload(apns_env):
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["topic"] = request.headers.get("apns-topic")
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    sender = make_sender(handler)
    assert sender.configured
    assert sender.send("abc123", "Last night", "You slept 7h") == "ok"
    assert captured["path"] == "/3/device/abc123"
    assert captured["topic"] == "com.ktonini.ouracle"
    assert captured["auth"].startswith("bearer ey")
    assert captured["body"]["aps"]["alert"]["title"] == "Last night"


def test_unregistered_status(apns_env):
    sender = make_sender(lambda r: httpx.Response(410, json={"reason": "Unregistered"}))
    assert sender.send("dead", "t", "b") == "unregistered"


def test_notify_sends_to_all_and_drops_dead_tokens(apns_env, db_session):
    db_session.add(IngestState(key="apns_device:tok-live", value="iPhone"))
    db_session.add(IngestState(key="apns_device:tok-dead", value="Old phone"))
    db_session.commit()

    def handler(request):
        if "tok-dead" in request.url.path:
            return httpx.Response(410)
        return httpx.Response(200)

    assert notify.notify(db_session, "t", "b", apns=make_sender(handler)) is True
    remaining = notify.registered_device_tokens(db_session)
    assert set(remaining) == {"tok-live"}


def test_unconfigured_apns_falls_back_quietly(monkeypatch, db_session):
    monkeypatch.delenv("OURACLE_APNS_KEY", raising=False)
    monkeypatch.delenv("OURACLE_PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("OURACLE_PUSHOVER_USER", raising=False)
    # No channels at all -> returns False, no exception.
    assert notify.notify(db_session, "t", "b") is False
