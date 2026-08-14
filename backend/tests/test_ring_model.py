"""The learned staging model."""

import json

from backend.src.ring_events.model import Forest, FEATURES, featurise_night, fit


def _night(n=60):
    """A crude but separable night: deep runs slow and still, REM faster and
    more variable, wake obvious in movement."""
    rows, labels = [], []
    for i in range(n):
        if i % 4 == 0:
            hr, move, ratio, stage = 55.0, 0.01, 0.9, "deep"
        elif i % 4 == 1:
            hr, move, ratio, stage = 68.0, 0.02, 2.4, "rem"
        elif i % 4 == 2:
            hr, move, ratio, stage = 62.0, 0.03, 1.2, "light"
        else:
            hr, move, ratio, stage = 78.0, 0.90, 1.5, "awake"
        rows.append({
            "heart_rate": hr, "movement": move, "movement_peak": move * 3,
            "temperature": 34.0, "hrv": 30.0, "sdnn_rmssd": ratio,
            "pnn50": 0.1, "breath_irregularity": 0.3,
        })
        labels.append(stage)
    return rows, labels


def test_featurise_adds_night_relative_terms():
    rows, _ = _night(12)
    features = featurise_night(rows)
    assert len(features) == 12
    assert set(FEATURES).issubset(features[0].keys())
    # Position through the night runs 0 → 1.
    assert features[0]["progress"] == 0.0
    assert features[-1]["progress"] == 1.0
    # Heart rate is expressed against this night's own floor, not an absolute.
    assert features[0]["hr_from_floor"] >= 0


def test_featurise_tolerates_missing_signals():
    rows = [{"heart_rate": 60.0} for _ in range(6)]
    features = featurise_night(rows)
    assert len(features) == 6
    assert features[0]["temperature"] is None
    assert features[0]["hr_from_floor"] is not None


def test_no_heart_rate_yields_no_features():
    assert featurise_night([{"movement": 0.1}]) == []


def test_forest_learns_a_separable_night():
    rows, labels = _night()
    forest = fit(featurise_night(rows), labels, trees=20)
    predictions = [forest.predict(f) for f in featurise_night(rows)]
    correct = sum(p == a for p, a in zip(predictions, labels))
    assert correct / len(labels) > 0.8


def test_forest_round_trips_through_json():
    rows, labels = _night()
    forest = fit(featurise_night(rows), labels, trees=10)
    revived = Forest.from_json(json.loads(json.dumps(forest.to_json())))
    for features in featurise_night(rows):
        assert revived.predict(features) == forest.predict(features)


def test_probabilities_sum_to_one():
    rows, labels = _night()
    forest = fit(featurise_night(rows), labels, trees=10)
    proba = forest.predict_proba(featurise_night(rows)[0])
    assert abs(sum(proba) - 1.0) < 1e-9
    assert len(proba) == len(forest.stages)


def test_fit_is_deterministic():
    rows, labels = _night()
    a = fit(featurise_night(rows), labels, trees=10)
    b = fit(featurise_night(rows), labels, trees=10)
    assert a.to_json() == b.to_json()


def test_missing_features_fall_back_to_training_medians():
    rows, labels = _night()
    forest = fit(featurise_night(rows), labels, trees=10)
    # An all-empty epoch must still classify rather than raise.
    assert forest.predict({name: None for name in FEATURES}) in forest.stages


def test_staging_uses_the_model_when_one_exists(tmp_path, monkeypatch):
    """A fitted model must actually be picked up by staging, and a server with
    no labels must still stage using the thresholds."""
    from datetime import datetime, timedelta, timezone

    from backend.src.ring_events import staging

    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(staging, "_MODEL_CACHE", (None, None))
    assert staging.load_model() is None  # nothing trained yet

    rows, labels = _night()
    forest = fit(featurise_night(rows), labels, trees=10)
    (tmp_path / "sleep_model.json").write_text(json.dumps(forest.to_json()))
    monkeypatch.setattr(staging, "_MODEL_CACHE", (None, None))
    assert staging.load_model() is not None

    start = datetime(2026, 8, 14, 23, 0, tzinfo=timezone.utc)
    epochs = [
        staging.Epoch(
            start=start + timedelta(minutes=5 * i),
            movement=row["movement"],
            heart_rate=row["heart_rate"],
            hr_variability=row["hrv"],
            movement_peak=row["movement_peak"],
            temperature=row["temperature"],
            sdnn_rmssd=row["sdnn_rmssd"],
            pnn50=row["pnn50"],
            breath_irregularity=row["breath_irregularity"],
        )
        for i, row in enumerate(rows)
    ]
    staged = staging.stage_epochs(epochs)
    assert len(staged) == len(epochs)
    # The model separates these; the thresholds alone would not find wake here.
    assert {e["stage"] for e in staged} & {"deep", "rem", "awake"}
    assert staging.summarise(staged)["method"] == "ouracle-model-v1"


def test_a_corrupt_model_falls_back_instead_of_failing(tmp_path, monkeypatch):
    from backend.src.ring_events import staging

    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    (tmp_path / "sleep_model.json").write_text("not json")
    monkeypatch.setattr(staging, "_MODEL_CACHE", (None, None))
    assert staging.load_model() is None
