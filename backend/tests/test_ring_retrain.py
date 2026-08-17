"""Guarded nightly retraining."""

import json

import pytest

from backend.src.ring_events import retrain as retrain_mod
from backend.src.ring_events.retrain import installed_meta, retrain


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *_):
        return self

    def all(self):
        return self._rows


def _dataset(days, per_night=40):
    """Paired rows spanning `days`, separable enough to train on."""
    rows = []
    for day in days:
        for i in range(per_night):
            stage = ["deep", "light", "rem", "awake"][i % 4]
            rows.append({
                "day": day,
                "t": f"2026-08-{day[-2:]}T{i // 12:02d}:{(i % 12) * 5:02d}:00+00:00",
                "heart_rate": {"deep": 55.0, "light": 62.0, "rem": 68.0, "awake": 78.0}[stage],
                "movement": {"deep": 0.01, "light": 0.03, "rem": 0.02, "awake": 0.9}[stage],
                "movement_peak": 0.1,
                "temperature": 34.0,
                "hrv": 30.0,
                "sdnn_rmssd": {"deep": 0.9, "light": 1.2, "rem": 2.4, "awake": 1.5}[stage],
                "pnn50": 0.1,
                "breath_irregularity": 0.3,
                "label": stage,
            })
    return rows


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    return tmp_path


def _patch_dataset(monkeypatch, rows):
    monkeypatch.setattr(retrain_mod, "build_dataset", lambda db: rows)


def test_no_paired_nights_does_nothing(data_dir, monkeypatch):
    _patch_dataset(monkeypatch, [])
    result = retrain(None)
    assert result["trained"] is False
    assert "no paired nights" in result["reason"]
    assert not (data_dir / "sleep_model.json").exists()


def test_first_run_trains_and_records_its_nights(data_dir, monkeypatch):
    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    result = retrain(None)
    assert result["trained"] is True
    meta = installed_meta()
    assert meta["nights"] == ["2026-08-05", "2026-08-06", "2026-08-07"]
    assert meta["epochs"] == 120
    assert meta["balanced"] is not None


def test_second_run_with_nothing_new_is_a_no_op(data_dir, monkeypatch):
    rows = _dataset(["2026-08-05", "2026-08-06", "2026-08-07"])
    _patch_dataset(monkeypatch, rows)
    retrain(None)
    written = (data_dir / "sleep_model.json").read_text()

    result = retrain(None)
    assert result["trained"] is False
    assert "no new nights" in result["reason"]
    # Byte-identical: an unattended job must not churn the model for nothing.
    assert (data_dir / "sleep_model.json").read_text() == written


def test_a_new_night_triggers_a_retrain(data_dir, monkeypatch):
    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    retrain(None)

    _patch_dataset(
        monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"])
    )
    result = retrain(None)
    assert result["trained"] is True
    assert result["new_nights"] == ["2026-08-08"]
    assert installed_meta()["epochs"] == 160


def test_a_model_that_cannot_beat_the_baseline_is_refused(data_dir, monkeypatch):
    """Unattended retraining must not install a model no better than answering
    "light" for every epoch."""
    from backend.src.ring_events import training

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06"]))
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 2,
            "model": {"balanced": 0.25, "accuracy": 0.45},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    result = retrain(None)
    assert result["trained"] is False
    assert "baseline" in result["reason"]
    assert not (data_dir / "sleep_model.json").exists()


def test_a_regression_against_the_installed_model_is_refused(data_dir, monkeypatch):
    """A worse fit must not silently replace a good one."""
    from backend.src.ring_events import training

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    assert retrain(None)["trained"] is True
    good = installed_meta()["balanced"]
    assert good > 0.3

    _patch_dataset(
        monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"])
    )
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 4,
            "model": {"balanced": good - 0.2, "accuracy": 0.3},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    result = retrain(None)
    assert result["trained"] is False
    assert "worse than the installed" in result["reason"]
    # The good model is untouched.
    assert installed_meta()["balanced"] == good


def test_force_overrides_the_guard(data_dir, monkeypatch):
    from backend.src.ring_events import training

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06"]))
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 2,
            "model": {"balanced": 0.1, "accuracy": 0.2},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    assert retrain(None, force=True)["trained"] is True


def test_installed_meta_survives_a_corrupt_model(data_dir):
    (data_dir / "sleep_model.json").write_text("not json")
    assert installed_meta() == {}


def test_a_tuning_change_retrains_even_with_no_new_nights(data_dir, monkeypatch):
    """Otherwise a parameter change is silently ignored: the nights have not
    moved, so nothing looks stale and the old model keeps serving."""
    from backend.src.ring_events import model

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    assert retrain(None)["trained"] is True
    assert retrain(None)["trained"] is False  # nothing new, as expected

    monkeypatch.setattr(model, "DEFAULT_CLASS_WEIGHT_POWER", 0.5)
    result = retrain(None)
    assert result["trained"] is True
    assert installed_meta()["config"]["class_weight_power"] == 0.5


def test_a_better_calibrated_fit_is_accepted_despite_lower_recall(data_dir, monkeypatch):
    """Recall and nightly totals are different things. A fit that trades one
    for the other on purpose must not be blocked by a guard that only watches
    recall — that would freeze in whichever trade happened to ship first."""
    from backend.src.ring_events import training

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 3,
            "model": {"balanced": 0.72, "accuracy": 0.70, "mean_abs_bias": 18.0},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    assert retrain(None)["trained"] is True
    assert installed_meta()["mean_abs_bias"] == 18.0

    # Much worse recall, but the nightly totals are far closer.
    _patch_dataset(
        monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"])
    )
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 4,
            "model": {"balanced": 0.60, "accuracy": 0.65, "mean_abs_bias": 4.0},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    assert retrain(None)["trained"] is True


def test_a_fit_worse_at_both_is_still_refused(data_dir, monkeypatch):
    from backend.src.ring_events import training

    _patch_dataset(monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07"]))
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 3,
            "model": {"balanced": 0.72, "accuracy": 0.70, "mean_abs_bias": 8.0},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    retrain(None)

    _patch_dataset(
        monkeypatch, _dataset(["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"])
    )
    monkeypatch.setattr(
        training, "cross_validate",
        lambda db, dataset=None: {
            "nights": 4,
            "model": {"balanced": 0.60, "accuracy": 0.65, "mean_abs_bias": 20.0},
            "majority": {"balanced": 0.25, "accuracy": 0.45},
        },
    )
    result = retrain(None)
    assert result["trained"] is False
    assert "worse than the installed" in result["reason"]
