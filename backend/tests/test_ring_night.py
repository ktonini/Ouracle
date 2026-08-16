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


def test_lowest_hr_ignores_single_outlier_beats(db_session):
    """A stray long interval must not be reported as the resting rate."""
    _sync(db_session, 0)
    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    base = to_ring_ds(start, EPOCH) + 600
    # Steady ~60 bpm, plus one 1999 ms interval (would read as 30 bpm).
    db_session.add(
        RingEventRaw(
            id="60-a", tag=0x60, timestamp=base, body="",
            decoded={"ibi_ms": [1000, 1000, 1999, 1000, 1000, 1000]},
        )
    )
    db_session.commit()
    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, tzinfo=timezone.utc)
    )
    assert night["lowest_hr"] > 45  # not the 30 bpm artefact


def test_movement_subsamples_do_not_clobber_the_clock(db_session):
    """Regression: a loop variable named `offset` overwrote the clock offset,
    so every timestamp after the first movement event landed in 1970."""
    _sync(db_session, 0)
    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    base = to_ring_ds(start, EPOCH)
    # Movement first, then heart rate — the order that triggered the bug.
    db_session.add(
        RingEventRaw(
            id="72-x", tag=0x72, timestamp=base + 60, body="",
            decoded={"acm_mad": [0.1] * 6},
        )
    )
    db_session.add(
        RingEventRaw(
            id="60-x", tag=0x60, timestamp=base + 1200, body="",
            decoded={"ibi_ms": [1000] * 6},
        )
    )
    db_session.commit()

    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, tzinfo=timezone.utc)
    )
    assert night["heart_rate"], "heart rate should be present"
    for point in night["heart_rate"] + night["movement"]:
        assert point["t"].startswith("2026-08-05"), point["t"]


def test_ibi_features_separate_steady_from_erratic_beats():
    """Deep sleep's metronomic beats and REM's erratic ones must not look alike."""
    from backend.src.ring_events.night import _ibi_features

    # Beat-to-beat jitter around a fixed mean: high RMSSD, low SDNN/RMSSD.
    steady = [1000 + (30 if i % 2 else -30) for i in range(60)]
    # Slow drift with little beat-to-beat change: the REM direction.
    drifting = [1000 + i * 8 for i in range(60)]

    steady_features = _ibi_features(steady)
    drifting_features = _ibi_features(drifting)
    assert steady_features["pnn50"] > 0.9
    assert drifting_features["pnn50"] == 0.0
    assert drifting_features["sdnn_rmssd"] > steady_features["sdnn_rmssd"]


def test_ibi_features_need_enough_beats():
    from backend.src.ring_events.night import _ibi_features

    assert _ibi_features([1000] * 5) is None
    assert _ibi_features([]) is None


def test_breath_irregularity_rises_with_erratic_respiration():
    """Evenly spaced respiratory waves score lower than jumbled ones."""
    import math

    from backend.src.ring_events.night import _breath_irregularity

    regular = [round(1000 + 40 * math.sin(i * 2 * math.pi / 12)) for i in range(200)]
    # Same amplitude, but the breath period keeps changing.
    erratic = []
    phase = 0.0
    for index in range(200):
        period = 6 + (index // 20) % 14
        phase += 2 * math.pi / period
        erratic.append(round(1000 + 40 * math.sin(phase)))

    assert _breath_irregularity(erratic) > _breath_irregularity(regular)


def test_night_exposes_per_bucket_ibi_features(db_session):
    _sync(db_session, 0)
    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    db_session.add(
        RingEventRaw(
            id="60-f", tag=0x60, timestamp=to_ring_ds(start, EPOCH) + 60, body="",
            decoded={"ibi_ms": [1000 + (20 if i % 2 else -20) for i in range(40)]},
        )
    )
    db_session.commit()
    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, tzinfo=timezone.utc)
    )
    assert night["ibi_features"]
    features = next(iter(night["ibi_features"].values()))
    assert features["rmssd"] > 0
    assert "breath_irregularity" in features


def test_breath_rate_recovers_a_known_breathing_frequency():
    """A synthetic respiratory wave at a known rate must read back as that
    rate — beats are not a clock, so the cycle length has to come from the
    intervals themselves."""
    import math

    from backend.src.ring_events.night import _breath_rate

    # 60 bpm heart rate (1000 ms intervals) modulated at 12 breaths/min:
    # one breath every 5 seconds, so every 5 beats.
    beats = [round(1000 + 40 * math.sin(i * 2 * math.pi / 5)) for i in range(300)]
    rate = _breath_rate(beats)
    assert rate is not None
    assert 11.0 <= rate <= 13.0, rate


def test_breath_rate_tracks_a_faster_rhythm():
    import math

    from backend.src.ring_events.night import _breath_rate

    # One breath every 3 beats at 1000 ms => 20 breaths/min.
    beats = [round(1000 + 40 * math.sin(i * 2 * math.pi / 3)) for i in range(300)]
    rate = _breath_rate(beats)
    assert rate is not None
    assert 18.0 <= rate <= 22.0, rate


def test_breath_rate_is_none_without_a_usable_wave():
    from backend.src.ring_events.night import _breath_rate

    assert _breath_rate([1000] * 200) is None   # flat: no peaks
    assert _breath_rate([1000] * 10) is None    # too few beats


def test_breath_rate_rejects_an_implausible_reading():
    """Peak detection latching onto something that isn't breathing must report
    nothing rather than a number."""
    import math

    from backend.src.ring_events.night import _breath_rate

    # A peak every other beat at 1000 ms would be 30/min — still plausible —
    # but at 300 ms intervals it implies 100 breaths a minute.
    beats = [round(300 + 20 * math.sin(i * math.pi)) for i in range(200)]
    assert _breath_rate(beats) is None


def test_night_features_include_breath_rate(db_session):
    _sync(db_session, 0)
    import math

    start = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    beats = [round(1000 + 40 * math.sin(i * 2 * math.pi / 5)) for i in range(120)]
    db_session.add(
        RingEventRaw(
            id="60-br", tag=0x60, timestamp=to_ring_ds(start, EPOCH) + 60, body="",
            decoded={"ibi_ms": beats},
        )
    )
    db_session.commit()
    night = build_night(
        db_session, start, datetime(2026, 8, 5, 7, tzinfo=timezone.utc)
    )
    features = next(iter(night["ibi_features"].values()))
    assert features["breath_rate"] is not None
    assert 10 <= features["breath_rate"] <= 14


def test_a_spurious_peak_does_not_double_the_breathing_rate():
    """Noise splitting one breath in two is what made the rate read high; a
    minimum cycle length is what stops it."""
    import math

    from backend.src.ring_events.night import _breath_rate

    # 12 breaths/min, with a small ripple riding on top that creates an extra
    # local maximum inside each breath.
    beats = [
        round(1000 + 40 * math.sin(i * 2 * math.pi / 5) + 6 * math.sin(i * 2 * math.pi / 2.5))
        for i in range(400)
    ]
    rate = _breath_rate(beats)
    assert rate is not None
    assert 11.0 <= rate <= 13.5, rate  # not ~24
