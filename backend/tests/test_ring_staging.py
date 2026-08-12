"""Locally derived sleep staging."""

from datetime import datetime, timedelta, timezone

from backend.src.ring_events.staging import (
    Epoch,
    _smooth,
    build_epochs,
    stage_epochs,
    summarise,
)

START = datetime(2026, 8, 5, 23, 0, tzinfo=timezone.utc)


def _epoch(index: int, movement: float, hr: float, hrv: float = 30.0) -> Epoch:
    return Epoch(
        start=START + timedelta(minutes=5 * index),
        movement=movement,
        heart_rate=hr,
        hr_variability=hrv,
    )


def test_movement_marks_wake():
    epochs = [_epoch(i, 0.02, 60) for i in range(6)]
    epochs[3] = _epoch(3, 2.5, 75)  # a big movement burst
    stages = [e["stage"] for e in stage_epochs(epochs)]
    assert stages[3] == "awake"


def test_low_hr_still_night_is_deep():
    # Mostly typical, with a stretch at the night's floor and no movement.
    epochs = [_epoch(i, 0.02, 70, 30) for i in range(10)]
    for i in range(3, 6):
        epochs[i] = _epoch(i, 0.01, 55, 20)
    stages = [e["stage"] for e in stage_epochs(epochs)]
    assert stages[4] == "deep"


def test_elevated_variable_hr_without_movement_is_rem():
    epochs = [_epoch(i, 0.02, 60, 25) for i in range(10)]
    for i in range(6, 9):
        epochs[i] = _epoch(i, 0.02, 72, 65)  # higher and more variable
    stages = [e["stage"] for e in stage_epochs(epochs)]
    assert "rem" in stages[6:9]


def test_default_stage_is_light():
    epochs = [_epoch(i, 0.03, 64, 30) for i in range(6)]
    assert set(e["stage"] for e in stage_epochs(epochs)) == {"light"}


def test_single_epoch_flicker_is_smoothed():
    """A lone deviating epoch between matching neighbours is noise."""
    staged = _smooth([
        {"stage": "light", "confidence": 0.5},
        {"stage": "deep", "confidence": 0.6},
        {"stage": "light", "confidence": 0.5},
    ])
    assert [e["stage"] for e in staged] == ["light", "light", "light"]
    assert staged[1]["confidence"] <= 0.4  # marked less certain


def test_wake_epochs_are_never_smoothed_away():
    """Brief awakenings are real and must survive smoothing."""
    staged = _smooth([
        {"stage": "light", "confidence": 0.5},
        {"stage": "awake", "confidence": 0.7},
        {"stage": "light", "confidence": 0.5},
    ])
    assert staged[1]["stage"] == "awake"


def test_genuine_transitions_are_kept():
    """Two epochs of the same stage is a transition, not a flicker."""
    staged = _smooth([
        {"stage": "light", "confidence": 0.5},
        {"stage": "deep", "confidence": 0.6},
        {"stage": "deep", "confidence": 0.6},
        {"stage": "light", "confidence": 0.5},
    ])
    assert [e["stage"] for e in staged] == ["light", "deep", "deep", "light"]


def test_summary_counts_minutes_and_efficiency():
    staged = [
        {"stage": "deep"}, {"stage": "deep"}, {"stage": "light"},
        {"stage": "rem"}, {"stage": "awake"},
    ]
    summary = summarise(staged)
    assert summary["deep_minutes"] == 10
    assert summary["asleep_minutes"] == 20
    assert summary["awake_minutes"] == 5
    assert summary["efficiency_percent"] == 80
    assert summary["method"] == "ouracle-local-v1"


def test_build_epochs_joins_series_on_timestamp():
    t0 = START.isoformat()
    t1 = (START + timedelta(minutes=5)).isoformat()
    epochs = build_epochs(
        heart_rate=[{"t": t0, "value": 60.0}, {"t": t1, "value": 62.0}],
        movement=[{"t": t0, "value": 0.05}],
        variability={t0: 33.0},
    )
    assert len(epochs) == 2
    assert epochs[0].heart_rate == 60.0
    assert epochs[0].movement == 0.05
    assert epochs[0].hr_variability == 33.0
    assert epochs[1].movement is None  # missing movement is tolerated


def test_no_heart_rate_yields_no_stages():
    assert stage_epochs([]) == []


def test_flat_night_is_not_all_deep():
    """No heart-rate variation means no basis for staging beyond wake."""
    epochs = [_epoch(i, 0.02, 64, 30) for i in range(8)]
    staged = stage_epochs(epochs)
    assert set(e["stage"] for e in staged) == {"light"}
    assert all(e["confidence"] <= 0.3 for e in staged)  # flagged as low-confidence
