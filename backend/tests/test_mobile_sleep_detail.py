"""/api/mobile/sleep/{day}: per-session sleep detail for the day view."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.database import get_db
from backend.src.models import Base, SleepSession

HEADERS = {"Authorization": "Bearer detail-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    monkeypatch.setenv("OURACLE_MOBILE_TOKEN", "detail-token")
    from backend.src.mobile_api_app import create_mobile_api_app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        SleepSession(
            id="sleep-1",
            day=date(2026, 8, 5),
            type="long_sleep",
            bedtime_start=datetime(2026, 8, 4, 23, 5),
            bedtime_end=datetime(2026, 8, 5, 7, 10),
            efficiency=88,
            total_sleep_duration=26400,
            deep_sleep_duration=5400,
            rem_sleep_duration=6600,
            light_sleep_duration=14400,
            awake_time=2700,
            average_heart_rate=58.0,
            average_hrv=62,
            sleep_phase_5_min="443322221111222333",
            hr_data={"interval": 300.0, "items": [60, 58, None, 55]},
            hrv_data={"interval": 300.0, "items": [50, 62, 70]},
        )
    )
    session.commit()

    app = create_mobile_api_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def test_returns_sessions_with_sequences(client):
    response = client.get("/api/mobile/sleep/2026-08-05", headers=HEADERS)
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    s = sessions[0]
    assert s["type"] == "long_sleep"
    assert s["sleep_phase_5_min"] == "443322221111222333"
    assert s["hr_data"]["items"] == [60, 58, None, 55]
    assert s["hrv_data"]["interval"] == 300.0
    assert s["deep_sleep_duration"] == 5400


def test_empty_day_returns_empty_list(client):
    response = client.get("/api/mobile/sleep/2026-08-06", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_requires_token(client):
    assert client.get("/api/mobile/sleep/2026-08-05").status_code == 401
