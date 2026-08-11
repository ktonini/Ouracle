"""Pairing ring features with cloud hypnogram labels."""

from datetime import date, datetime, timezone

from backend.src.models import RingEventRaw, SleepSession
from backend.src.ring_events.training import (
    build_dataset,
    evaluate_heuristic,
    labelled_epochs,
)
from backend.src.ring_events.night import to_ring_ds

EPOCH = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc).timestamp()


def _session(**kw):
    values = dict(
        id="s1", day=date(2026, 8, 5),
        bedtime_start=datetime(2026, 8, 5, 6, 0),
        bedtime_end=datetime(2026, 8, 5, 6, 30),
        sleep_phase_5_min="442211",
    )
    values.update(kw)
    return SleepSession(**values)


def test_cloud_phase_codes_decoded(db_session):
    epochs = labelled_epochs(db_session, _session())
    assert [stage for _, stage in epochs] == [
        "awake", "awake", "light", "light", "deep", "deep"
    ]
    # Epochs advance in 5-minute steps from bedtime.
    assert (epochs[1][0] - epochs[0][0]).total_seconds() == 300


def test_no_labels_without_hypnogram(db_session):
    assert labelled_epochs(db_session, _session(sleep_phase_5_min=None)) == []


def test_dataset_empty_without_ring_data(db_session):
    db_session.add(_session())
    db_session.commit()
    assert build_dataset(db_session) == []


def test_dataset_pairs_features_with_labels(db_session):
    db_session.add(_session())
    db_session.add(
        RingEventRaw(
            id="42-0", tag=0x42, timestamp=0, body="",
            decoded={"unix_time": int(EPOCH)},
        )
    )
    start = datetime(2026, 8, 5, 6, 2, tzinfo=timezone.utc)
    db_session.add(
        RingEventRaw(
            id="60-1", tag=0x60, timestamp=to_ring_ds(start, EPOCH), body="",
            decoded={"ibi_ms": [1000] * 6},
        )
    )
    db_session.commit()

    rows = build_dataset(db_session)
    assert rows, "expected at least one paired epoch"
    assert rows[0]["label"] in {"deep", "light", "rem", "awake"}
    assert rows[0]["heart_rate"] == 60.0

    result = evaluate_heuristic(db_session)
    assert result["paired_epochs"] >= 1
    assert 0.0 <= result["accuracy"] <= 1.0
