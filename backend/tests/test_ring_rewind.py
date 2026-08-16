"""The drain rewinding itself when a scored night has no ring data."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.database import get_db
from backend.src.models import Base, IngestState, RingEventRaw, SleepSession
from backend.src.ring_events.night import to_ring_ds

HEADERS = {"Authorization": "Bearer ring-token"}
EPOCH = 1_700_000_000.0


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


def _setup(db, cursor_at, backlog="0"):
    db.add(
        RingEventRaw(id="42-0", tag=0x42, timestamp=0, body="",
                     decoded={"unix_time": EPOCH})
    )
    db.add(IngestState(key="ring_events:cursor", value=str(cursor_at)))
    db.add(IngestState(key="ring_events:bytes_left", value=backlog))
    db.commit()


def _session(db, day, start, hours=7, labels=60):
    db.add(
        SleepSession(
            id=f"s-{day}", day=date.fromisoformat(day),
            bedtime_start=start.replace(tzinfo=None),
            bedtime_end=(start + timedelta(hours=hours)).replace(tzinfo=None),
            sleep_phase_5_min="2" * labels,
        )
    )
    db.commit()


def _cover(db, start, hours):
    for step in range(int(hours * 12)):
        ds = to_ring_ds(start + timedelta(minutes=step * 5), EPOCH)
        db.add(RingEventRaw(id=f"60-{ds}", tag=0x60, timestamp=ds, body="00"))
    db.commit()


def _state(client):
    return client.get("/api/mobile/ring-events/state", headers=HEADERS).json()


def test_no_rewind_when_every_night_is_covered(client):
    start = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(start + timedelta(days=2), EPOCH))
    _session(client.session, "2026-08-09", start)
    _cover(client.session, start, 7)

    state = _state(client)
    assert state["rewound_for"] is None
    assert state["cursor"] == to_ring_ds(start + timedelta(days=2), EPOCH)


def test_rewinds_past_a_missing_night(client):
    """The exact failure: the cursor advanced beyond a night we never read."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    ahead = to_ring_ds(missing + timedelta(days=1), EPOCH)
    _setup(client.session, ahead)
    _session(client.session, "2026-08-12", missing)

    state = _state(client)
    assert state["rewound_for"] == "2026-08-12"
    assert state["cursor"] < ahead
    assert state["cursor"] <= to_ring_ds(missing, EPOCH)


def test_no_rewind_while_a_backlog_remains(client):
    """Mid-drain, let it finish rather than sending it round again."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    ahead = to_ring_ds(missing + timedelta(days=1), EPOCH)
    _setup(client.session, ahead, backlog="50000")
    _session(client.session, "2026-08-12", missing)

    assert _state(client)["rewound_for"] is None


def test_a_night_ahead_of_the_cursor_is_left_alone(client):
    """The drain will reach it on its own; rewinding would lose progress."""
    behind = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(behind, EPOCH))
    _session(client.session, "2026-08-12", datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc))

    assert _state(client)["rewound_for"] is None


def test_most_recent_missing_night_goes_first(client):
    """Cheapest to re-read and likeliest to still be in the ring's buffer."""
    old = datetime(2026, 8, 7, 22, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(recent + timedelta(days=1), EPOCH))
    _session(client.session, "2026-08-07", old)
    _session(client.session, "2026-08-12", recent)

    assert _state(client)["rewound_for"] == "2026-08-12"


def _failed_sync(client):
    """A sync that reached the ring and came back with nothing."""
    client.post(
        "/api/mobile/ring-events",
        json={"events": [], "status": "auto: nothing new", "bytes_left": 0},
        headers=HEADERS,
    )


def test_a_night_the_ring_no_longer_holds_is_eventually_abandoned(client):
    """Otherwise the drain re-reads the same span forever chasing data that
    aged out of the ring's buffer."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(missing + timedelta(days=1), EPOCH))
    _session(client.session, "2026-08-12", missing)

    seen = []
    for _ in range(5):
        seen.append(_state(client)["rewound_for"])
        _failed_sync(client)
    assert seen[:3] == ["2026-08-12"] * 3
    assert seen[3:] == [None, None]


def test_progress_keeps_the_rewind_alive(client):
    """A rewind that is recovering data must not be cut off by the cap."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(missing + timedelta(days=1), EPOCH))
    _session(client.session, "2026-08-12", missing)

    for _ in range(2):
        assert _state(client)["rewound_for"] == "2026-08-12"
        _failed_sync(client)
    # A pass lands part of the night: coverage improved, so the budget resets.
    _cover(client.session, missing, 3)
    for _ in range(3):
        assert _state(client)["rewound_for"] == "2026-08-12"
        _failed_sync(client)


def test_uploading_does_not_rewind_or_spend_attempts(client):
    """A chunk upload returns state too; it must not send the drain backwards
    mid-pass or burn the budget."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    ahead = to_ring_ds(missing + timedelta(days=1), EPOCH)
    _setup(client.session, ahead)
    _session(client.session, "2026-08-12", missing)

    posted = client.post(
        "/api/mobile/ring-events",
        json={"events": [], "status": "auto: ok", "bytes_left": 0},
        headers=HEADERS,
    ).json()
    assert posted["rewound_for"] is None
    assert posted["cursor"] == ahead
    assert client.session.get(IngestState, "ring_events:rewind") is None


def test_reading_state_repeatedly_does_not_spend_the_budget(client):
    """The app reads this endpoint more than once per sync. Only a drain that
    actually ran and recovered nothing should count against the budget."""
    missing = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    _setup(client.session, to_ring_ds(missing + timedelta(days=1), EPOCH))
    _session(client.session, "2026-08-12", missing)

    # Ten reads with no sync in between still offer the same rewind.
    assert all(_state(client)["rewound_for"] == "2026-08-12" for _ in range(10))

    # Each real sync attempt that recovers nothing costs one.
    for _ in range(3):
        client.post(
            "/api/mobile/ring-events",
            json={"events": [], "status": "auto failed: out of range"},
            headers=HEADERS,
        )
        _state(client)
    assert _state(client)["rewound_for"] is None
