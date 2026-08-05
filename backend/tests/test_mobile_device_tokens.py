"""Per-device token auth for the mobile API."""

import pytest
from fastapi.testclient import TestClient


def _make_client(db_session=None):
    # TestClient serves sync endpoints from a worker thread; the shared
    # conftest session is thread-bound, so build a thread-safe one here.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.src.database import get_db
    from backend.src.mobile_api_app import create_mobile_api_app
    from backend.src.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    app = create_mobile_api_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    monkeypatch.setenv("OURACLE_MOBILE_TOKEN", "legacy-shared-token")
    monkeypatch.setenv(
        "OURACLE_MOBILE_TOKENS", "ios-keith:ios-token-1, android:droid-token-2"
    )
    return _make_client()


def _ping(client, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/mobile/ping", headers=headers)


def test_each_device_token_authenticates(client):
    assert _ping(client, "ios-token-1").status_code == 200
    assert _ping(client, "droid-token-2").status_code == 200


def test_legacy_shared_token_still_works(client):
    assert _ping(client, "legacy-shared-token").status_code == 200


def test_unknown_token_rejected(client):
    assert _ping(client, "not-a-token").status_code == 401
    assert _ping(client, None).status_code == 401


def test_device_tokens_alone_enable_api(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    monkeypatch.delenv("OURACLE_MOBILE_TOKEN", raising=False)
    monkeypatch.setenv("OURACLE_MOBILE_TOKENS", "solo:only-token")
    client = _make_client()
    assert _ping(client, "only-token").status_code == 200
    assert _ping(client, "wrong").status_code == 401
