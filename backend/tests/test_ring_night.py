"""Assembling a night from ring events."""

from datetime import datetime, timezone

import pytest

from backend.src.models import RingEventRaw
from backend.src.ring_events.night import (
    build_night,
    detected_bedtimes,
    ring_clock_offset,
    to_ring_ds,
)

# Ring powered on at this instant; event ds are relative to it.
EPOCH = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc).timestamp()


def _sync(db, ds: int):
    db.add(
        RingEventRaw(
            id=f"42-{ds}", tag=0x42, timestamp=ds, body="",
            decoded={"unix_time": int(EPOCH + ds / 10)},
        )
    )


def test_clock_offset_from_time_sync(db_session):
    _sync(db_session, 1000)
    _sync(db_session, 5000)
    db_session.commit()
    assert ring_clock_offset(db_session) == pytest.approx(EPOCH, abs=1)


def test_offset_is_none_without_time_sync(db_session):
    assert ring_clock_offset(db_session) is None
    night = build_night(
        db_session,
        datetime(2026, 8, 5, 6, tzinfo=timezone.utc),
        datetime(2026, 8, 5, 7, tzinfo=timezone.utc),
    )
    assert "error" in night  # cannot align without a reference


def test_night_series_from_ibi_and_movement(db_session):
    _sync(db_session, 0)
    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    ds = to_ring_ds(start, EPOCH) + 600  # a minute in
    # Six 1000 ms beats -> 60 bpm
    db_session.add(
        RingEventRaw(
            id="60-1", tag=0x60, timestamp=ds, body="",
            decoded={"ibi_ms": [1000] * 6},
        )
    )
    db_session.add(
        RingEventRaw(
            id="72-1", tag=0x72, timestamp=ds, body="",
            decoded={"acm_mad": [0.2, 0.4, 0.6, 0.2, 0.2, 0.2]},
        )
    )
    db_session.commit()

    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc)
    )
    assert night["beats"] == 6
    assert night["average_hr"] == 60
    assert night["lowest_hr"] == 60
    assert len(night["heart_rate"]) == 1
    assert night["heart_rate"][0]["value"] == 60.0
    assert night["movement"][0]["value"] == pytest.approx(0.3, abs=0.01)


def test_events_outside_the_window_are_excluded(db_session):
    _sync(db_session, 0)
    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    db_session.add(
        RingEventRaw(
            id="60-far", tag=0x60,
            timestamp=to_ring_ds(datetime(2026, 8, 5, 20, tzinfo=timezone.utc), EPOCH),
            body="", decoded={"ibi_ms": [1000] * 6},
        )
    )
    db_session.commit()
    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc)
    )
    assert night["beats"] == 0
    assert night["heart_rate"] == []


def test_detected_bedtimes_converted_to_wall_clock(db_session):
    _sync(db_session, 0)
    start_ds = to_ring_ds(datetime(2026, 8, 5, 6, tzinfo=timezone.utc), EPOCH)
    end_ds = to_ring_ds(datetime(2026, 8, 5, 13, tzinfo=timezone.utc), EPOCH)
    db_session.add(
        RingEventRaw(
            id="76-1", tag=0x76, timestamp=start_ds, body="",
            decoded={
                "bedtime_start_ds": start_ds,
                "bedtime_end_ds": end_ds,
                "duration_hours": 7.0,
            },
        )
    )
    db_session.commit()
    windows = detected_bedtimes(db_session)
    assert len(windows) == 1
    assert windows[0]["start"].startswith("2026-08-05T06:00")
    assert windows[0]["duration_hours"] == 7.0
