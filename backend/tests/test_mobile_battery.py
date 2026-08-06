"""Latest ring battery reading in the sync payload."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.database import get_db
from backend.src.models import Base, RingBattery

HEADERS = {"Authorization": "Bearer battery-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    monkeypatch.setenv("OURACLE_MOBILE_TOKEN", "battery-token")
    from backend.src.mobile_api_app import create_mobile_api_app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            RingBattery(
                timestamp=datetime(2026, 8, 5, 8, 0), level=64,
                charging=False, in_charger=False,
            ),
            RingBattery(
                timestamp=datetime(2026, 8, 5, 12, 30), level=58,
                charging=False, in_charger=False,
            ),
        ]
    )
    session.commit()

    app = create_mobile_api_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def test_sync_includes_latest_battery(client):
    payload = client.get("/api/mobile/sync", headers=HEADERS).json()
    battery = payload["ring_battery"]
    assert battery["level"] == 58  # newest reading wins
    assert battery["charging"] is False
    assert battery["timestamp"].startswith("2026-08-05T12:30")
