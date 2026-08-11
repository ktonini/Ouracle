"""Raw ring history-event upload and cursor bookkeeping."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.database import get_db
from backend.src.models import Base, RingEventRaw

HEADERS = {"Authorization": "Bearer ring-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    monkeypatch.setenv("OURACLE_MOBILE_TOKEN", "ring-token")
    from backend.src.mobile_api_app import create_mobile_api_app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    app = create_mobile_api_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    client.session = session
    return client


def test_state_starts_empty(client):
    state = client.get("/api/mobile/ring-events/state", headers=HEADERS).json()
    assert state["cursor"] == 0
    assert state["stored_events"] == 0
    assert state["latest_event_at"] is None
    assert state["last_attempt_at"] is None


def test_upload_stores_events_and_advances_cursor(client):
    body = {
        "events": [
            {"tag": 0x55, "timestamp": 1000, "body": "AABB"},
            {"tag": 0x41, "timestamp": 1200, "body": "ccdd"},
        ],
        "next_cursor": 1201,
    }
    state = client.post("/api/mobile/ring-events", json=body, headers=HEADERS).json()
    assert state["stored_events"] == 2
    assert state["cursor"] == 1201
    assert state["latest_event_at"] == 1200

    stored = client.session.query(RingEventRaw).order_by(RingEventRaw.timestamp).all()
    assert [e.tag for e in stored] == [0x55, 0x41]
    assert stored[0].body == "aabb"  # normalised to lower case
    assert stored[0].decoded is None  # decoding happens later


def test_reupload_is_idempotent(client):
    body = {"events": [{"tag": 0x55, "timestamp": 42, "body": "aa"}], "next_cursor": 43}
    client.post("/api/mobile/ring-events", json=body, headers=HEADERS)
    state = client.post("/api/mobile/ring-events", json=body, headers=HEADERS).json()
    assert state["stored_events"] == 1


def test_cursor_never_moves_backwards(client):
    client.post(
        "/api/mobile/ring-events",
        json={"events": [], "next_cursor": 5000},
        headers=HEADERS,
    )
    state = client.post(
        "/api/mobile/ring-events",
        json={"events": [], "next_cursor": 10},
        headers=HEADERS,
    ).json()
    assert state["cursor"] == 5000


def test_requires_token(client):
    assert client.get("/api/mobile/ring-events/state").status_code == 401
    assert client.post("/api/mobile/ring-events", json={"events": []}).status_code == 401


def test_records_attempt_status_even_when_empty(client):
    """Background sync must leave a trace, or a run of failures looks
    identical to 'nothing new'."""
    state = client.post(
        "/api/mobile/ring-events",
        json={"events": [], "status": "auto failed: ring unavailable"},
        headers=HEADERS,
    ).json()
    assert state["last_status"] == "auto failed: ring unavailable"
    assert state["last_added"] == 0
    assert state["last_attempt_at"] is not None
    assert state["cursor"] == 0  # a failed attempt must not move the bookmark


def test_successful_attempt_records_count(client):
    state = client.post(
        "/api/mobile/ring-events",
        json={
            "events": [{"tag": 0x60, "timestamp": 10, "body": "aa"}],
            "next_cursor": 11,
            "status": "manual: ok",
        },
        headers=HEADERS,
    ).json()
    assert state["last_status"] == "manual: ok"
    assert state["last_added"] == 1
    assert state["cursor"] == 11
