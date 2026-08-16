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
    client = TestClient(app)
    client.session = session
    return client


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


def test_ring_night_reports_breathing_rate(client):
    """Derived from the beat intervals, and reported as a median so one bad
    bucket cannot move it."""
    import math
    from datetime import datetime, timezone

    from backend.src.models import RingEventRaw
    from backend.src.ring_events.night import to_ring_ds

    epoch = 1_700_000_000.0
    client.session.add(
        RingEventRaw(id="42-0", tag=0x42, timestamp=0, body="",
                     decoded={"unix_time": epoch})
    )
    start = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
    # 12 breaths/min at 60 bpm, spread across several buckets.
    for bucket in range(8):
        when = to_ring_ds(start, epoch) + bucket * 3000
        beats = [round(1000 + 40 * math.sin(i * 2 * math.pi / 5)) for i in range(200)]
        client.session.add(
            RingEventRaw(id=f"60-{when}", tag=0x60, timestamp=when, body="",
                         decoded={"ibi_ms": beats})
        )
    client.session.commit()

    night = client.get("/api/mobile/ring-night/2026-08-16", headers=HEADERS).json()
    assert night["breath_rate"] is not None
    assert 10.0 <= night["breath_rate"] <= 14.0


def test_ring_night_omits_breathing_rate_without_enough_signal(client):
    """A time-aligned night with too few clean breath cycles reports nothing
    rather than a figure from two peaks."""
    from datetime import datetime, timezone

    from backend.src.models import RingEventRaw
    from backend.src.ring_events.night import to_ring_ds

    epoch = 1_700_000_000.0
    client.session.add(
        RingEventRaw(id="42-0", tag=0x42, timestamp=0, body="",
                     decoded={"unix_time": epoch})
    )
    start = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
    client.session.add(
        RingEventRaw(
            id="60-x", tag=0x60, timestamp=to_ring_ds(start, epoch) + 60, body="",
            decoded={"ibi_ms": [1000] * 40},  # flat: no respiratory wave
        )
    )
    client.session.commit()

    night = client.get("/api/mobile/ring-night/2026-08-16", headers=HEADERS).json()
    assert night["breath_rate"] is None
    assert night["error"] is None


def test_ring_night_without_any_ring_data_answers_cleanly(client):
    """An empty night is an answer, not a 500 — this is what a fresh install
    sees before the first sync."""
    response = client.get("/api/mobile/ring-night/2026-08-16", headers=HEADERS)
    assert response.status_code == 200
    night = response.json()
    assert night["error"]
    assert night["heart_rate"] == []
    assert night["breath_rate"] is None
