"""Pair ring-derived features with the cloud's hypnogram labels.

Oura's own per-5-minute staging is stored alongside our ring signals on the
same clock, which makes it a free label set: we can measure how the local
heuristic performs and, once enough nights are paired, fit a model that
reproduces the cloud's staging from ring data alone.

The value is that it keeps working after the labels stop — a subscription
lapse takes the labels away, not the capability learned from them.

    python -m backend.src.ring_events.training [--csv out.csv]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import SleepSession
from .night import build_night
from .staging import build_epochs, stage_epochs

logger = logging.getLogger("RingTraining")

# Oura's 5-minute phase encoding.
CLOUD_PHASES = {"1": "deep", "2": "light", "3": "rem", "4": "awake"}
EPOCH_SECONDS = 300


def labelled_epochs(db: Session, session: SleepSession) -> List[Tuple[datetime, str]]:
    """(epoch start, stage) from the cloud hypnogram for one session."""
    phases = session.sleep_phase_5_min
    if not phases or not session.bedtime_start:
        return []
    start = session.bedtime_start.replace(tzinfo=timezone.utc)
    out = []
    for index, code in enumerate(phases):
        stage = CLOUD_PHASES.get(code)
        if stage:
            out.append((start + timedelta(seconds=EPOCH_SECONDS * index), stage))
    return out


def build_dataset(db: Session) -> List[Dict[str, Any]]:
    """Feature rows for every night where ring data and labels overlap."""
    rows: List[Dict[str, Any]] = []

    for session in db.query(SleepSession).order_by(SleepSession.day).all():
        labels = labelled_epochs(db, session)
        if not labels:
            continue

        night = build_night(db, session.bedtime_start, session.bedtime_end)
        if night.get("error") or not night.get("heart_rate"):
            continue

        variability = night.get("hrv", {}) or {}
        by_time = {
            point["t"]: point["value"] for point in night.get("heart_rate", [])
        }
        movement_by_time = {
            point["t"]: point["value"] for point in night.get("movement", [])
        }
        peak_by_time = {
            point["t"]: point["value"] for point in night.get("movement_peak", [])
        }
        temp_by_time = {
            point["t"]: point["value"] for point in night.get("temperature", [])
        }
        features_by_time = night.get("ibi_features", {}) or {}
        # Our buckets sit on absolute 5-minute boundaries; the cloud's epochs
        # start at bedtime. Snap each label to the bucket containing it.
        for when, stage in labels:
            bucket = datetime.fromtimestamp(
                int(when.timestamp() // EPOCH_SECONDS) * EPOCH_SECONDS, timezone.utc
            ).isoformat()
            heart_rate = by_time.get(bucket)
            if heart_rate is None:
                continue
            rows.append(
                {
                    "day": str(session.day),
                    "t": bucket,
                    "heart_rate": heart_rate,
                    "movement": movement_by_time.get(bucket),
                    "movement_peak": peak_by_time.get(bucket),
                    "temperature": temp_by_time.get(bucket),
                    "hrv": variability.get(bucket),
                    "sdnn_rmssd": features_by_time.get(bucket, {}).get("sdnn_rmssd"),
                    "pnn50": features_by_time.get(bucket, {}).get("pnn50"),
                    "breath_irregularity": features_by_time.get(bucket, {}).get(
                        "breath_irregularity"
                    ),
                    "breath_rate": features_by_time.get(bucket, {}).get("breath_rate"),
                    "label": stage,
                }
            )
    return rows


def evaluate_heuristic(db: Session) -> Dict[str, Any]:
    """Score the current local staging against the cloud's labels."""
    dataset = build_dataset(db)
    if not dataset:
        return {"paired_epochs": 0}

    by_night: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        by_night.setdefault(row["day"], []).append(row)

    correct = 0
    total = 0
    confusion: Dict[str, Dict[str, int]] = {}

    for rows in by_night.values():
        rows.sort(key=lambda r: r["t"])
        epochs = build_epochs(
            [{"t": r["t"], "value": r["heart_rate"]} for r in rows],
            [
                {"t": r["t"], "value": r["movement"]}
                for r in rows
                if r["movement"] is not None
            ],
            {r["t"]: r["hrv"] for r in rows if r["hrv"] is not None},
            movement_peak=[
                {"t": r["t"], "value": r["movement_peak"]}
                for r in rows
                if r.get("movement_peak") is not None
            ],
            temperature=[
                {"t": r["t"], "value": r["temperature"]}
                for r in rows
                if r.get("temperature") is not None
            ],
            ibi_features={
                r["t"]: {
                    "sdnn_rmssd": r.get("sdnn_rmssd"),
                    "pnn50": r.get("pnn50"),
                    "breath_irregularity": r.get("breath_irregularity"),
                    "breath_rate": r.get("breath_rate"),
                }
                for r in rows
                if r.get("sdnn_rmssd") is not None
            },
        )
        # Force the thresholds: this function exists to score them.
        predictions = {
            e["t"]: e["stage"] for e in stage_epochs(epochs, use_model=False)
        }
        for row in rows:
            predicted = predictions.get(row["t"])
            if predicted is None:
                continue
            total += 1
            correct += predicted == row["label"]
            confusion.setdefault(row["label"], {}).setdefault(predicted, 0)
            confusion[row["label"]][predicted] += 1

    return {
        "paired_epochs": total,
        "nights": len(by_night),
        "accuracy": round(correct / total, 3) if total else None,
        "confusion": confusion,
    }


def model_config() -> Dict[str, Any]:
    """What the fit depends on besides the data.

    Recorded with the model so that changing a tuning constant retrains on the
    next run. Without this a parameter change is silently ignored — the nights
    have not changed, so nothing looks stale.
    """
    from .model import DEFAULT_CLASS_WEIGHT_POWER, DEFAULT_EMISSION_WEIGHT, FEATURES

    return {
        "emission_weight": DEFAULT_EMISSION_WEIGHT,
        "class_weight_power": DEFAULT_CLASS_WEIGHT_POWER,
        "features": list(FEATURES),
    }


def _by_night(dataset: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    nights: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        nights.setdefault(row["day"], []).append(row)
    for rows in nights.values():
        rows.sort(key=lambda r: r["t"])
    return nights


def _score(
    actual: List[str], predicted: List[str], nights: int = 1
) -> Dict[str, Any]:
    confusion: Dict[str, Dict[str, int]] = {}
    correct = 0
    for want, got in zip(actual, predicted):
        correct += want == got
        confusion.setdefault(want, {}).setdefault(got, 0)
        confusion[want][got] += 1

    # Per-epoch accuracy counts errors in both directions equally, so a model
    # can score well and still lean consistently one way. This is what a user
    # actually sees: minutes of each stage, per night, too many or too few.
    stages = set(actual) | set(predicted)
    bias = {
        stage: round(
            (predicted.count(stage) - actual.count(stage)) * EPOCH_SECONDS
            / 60 / max(nights, 1),
            1,
        )
        for stage in sorted(stages)
    }
    return {
        "minutes_bias": bias,
        # One number for "how wrong are the nightly totals", so calibration can
        # be compared between fits the way accuracy already is.
        "mean_abs_bias": round(
            sum(abs(v) for v in bias.values()) / max(len(bias), 1), 2
        ),
        "epochs": len(actual),
        "accuracy": round(correct / len(actual), 3) if actual else None,
        "confusion": confusion,
        # Mean per-class recall. Plain accuracy rewards answering "light"
        # everywhere, which is exactly the failure mode to avoid.
        "balanced": round(
            sum(
                confusion.get(stage, {}).get(stage, 0) / max(sum(confusion.get(stage, {}).values()), 1)
                for stage in set(actual)
            )
            / max(len(set(actual)), 1),
            3,
        ),
    }


def cross_validate(
    db: Session, dataset: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Leave-one-night-out. Epochs within a night are heavily correlated, so a
    random split would report a score the model could never reach in use."""
    from .model import featurise_night, fit

    nights = _by_night(build_dataset(db) if dataset is None else dataset)
    if len(nights) < 2:
        return {"nights": len(nights)}

    actual: List[str] = []
    predicted: List[str] = []
    majority: List[str] = []

    for held_out in nights:
        train_samples: List[Dict[str, Any]] = []
        train_labels: List[str] = []
        sequences: List[List[str]] = []
        for day, rows in nights.items():
            if day == held_out:
                continue
            night_labels = [row["label"] for row in rows]
            sequences.append(night_labels)
            for features, row in zip(featurise_night(rows), rows):
                train_samples.append(features)
                train_labels.append(row["label"])
        if not train_samples:
            continue

        forest = fit(train_samples, train_labels, sequences=sequences)
        most_common = max(set(train_labels), key=train_labels.count)

        rows = nights[held_out]
        features = featurise_night(rows)
        # Decode the night as a sequence: the held-out night's own labels are
        # never seen, only the transition structure of the training nights.
        decoded = forest.decode(features)
        for row, (stage, _) in zip(rows, decoded):
            actual.append(row["label"])
            predicted.append(stage)
            majority.append(most_common)

    return {
        "nights": len(nights),
        "model": _score(actual, predicted, nights=len(nights)),
        "majority": _score(actual, majority, nights=len(nights)),
    }


def train_model(
    db: Session,
    dataset: Optional[List[Dict[str, Any]]] = None,
    guard: bool = True,
) -> Dict[str, Any]:
    """Fit on every paired night and write the model beside the database.

    Guarded: a model that cannot beat answering "light" for every epoch is not
    worth shipping, and neither is one materially worse than what is already
    installed. Retraining runs unattended, so it must not be able to quietly
    replace a good model with a bad one.
    """
    import json
    from datetime import datetime, timezone

    from ..paths import get_user_data_dir
    from .model import featurise_night, fit

    rows = build_dataset(db) if dataset is None else dataset
    nights = _by_night(rows)
    samples: List[Dict[str, Any]] = []
    labels: List[str] = []
    sequences: List[List[str]] = []
    for night_rows in nights.values():
        sequences.append([row["label"] for row in night_rows])
        for features, row in zip(featurise_night(night_rows), night_rows):
            samples.append(features)
            labels.append(row["label"])
    if not samples:
        return {"trained": False, "reason": "no paired epochs"}

    scores = cross_validate(db, dataset=rows)
    fresh = (scores.get("model") or {}).get("balanced")
    fresh_bias = (scores.get("model") or {}).get("mean_abs_bias")
    baseline = (scores.get("majority") or {}).get("balanced")
    path = get_user_data_dir() / "sleep_model.json"

    previous: Optional[Dict[str, Any]] = None
    if path.exists():
        try:
            previous = json.loads(path.read_text()).get("meta")
        except Exception:
            previous = None

    if guard and fresh is not None and baseline is not None:
        if fresh <= baseline:
            return {
                "trained": False,
                "reason": f"balanced {fresh} does not beat baseline {baseline}",
                "scores": scores,
            }
        was = (previous or {}).get("balanced")
        was_bias = (previous or {}).get("mean_abs_bias")
        # A little movement between fits is normal; a real drop is not — but
        # recall is not the only thing that matters. A fit that reports the
        # nightly totals better has bought that with recall on purpose, and
        # refusing it would freeze in whichever trade happened to ship first.
        calibration_improved = (
            was_bias is not None
            and fresh_bias is not None
            and fresh_bias < was_bias
        )
        if was is not None and fresh < was - 0.05 and not calibration_improved:
            return {
                "trained": False,
                "reason": f"balanced {fresh} is worse than the installed {was}",
                "scores": scores,
            }

    forest = fit(samples, labels, sequences=sequences)
    blob = forest.to_json()
    blob["meta"] = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "nights": sorted(nights),
        "epochs": len(samples),
        "config": model_config(),
        "balanced": fresh,
        "mean_abs_bias": fresh_bias,
        "accuracy": (scores.get("model") or {}).get("accuracy"),
        "baseline_balanced": baseline,
    }
    path.write_text(json.dumps(blob))
    return {
        "trained": True,
        "path": str(path),
        "epochs": len(samples),
        "nights": len(nights),
        "balanced": fresh,
        "baseline": baseline,
        "previous_balanced": (previous or {}).get("balanced"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pair ring features with cloud labels.")
    parser.add_argument("--csv", help="Write the dataset to this path.")
    parser.add_argument("--cv", action="store_true", help="Leave-one-night-out scoring.")
    parser.add_argument("--train", action="store_true", help="Fit and save the model.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        dataset = build_dataset(db)
        logger.info("paired epochs: %d", len(dataset))
        if args.csv and dataset:
            import csv

            with open(args.csv, "w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(dataset[0].keys()))
                writer.writeheader()
                writer.writerows(dataset)
            logger.info("wrote %s", args.csv)

        if args.cv:
            scores = cross_validate(db)
            logger.info("leave-one-night-out over %d nights", scores.get("nights", 0))
            for name in ("majority", "model"):
                block = scores.get(name)
                if not block:
                    continue
                logger.info(
                    "  %-9s accuracy %s  balanced %s",
                    name, block["accuracy"], block["balanced"],
                )
                logger.info(
                    "      minutes/night vs cloud: %s",
                    ", ".join(
                        f"{stage} {value:+.0f}"
                        for stage, value in block["minutes_bias"].items()
                    ),
                )
                for actual, preds in sorted(block["confusion"].items()):
                    detail = ", ".join(f"{s} {c}" for s, c in sorted(preds.items()))
                    logger.info("      actual %-6s (%3d): %s",
                                actual, sum(preds.values()), detail)
        if args.train:
            logger.info("trained: %s", train_model(db))

        result = evaluate_heuristic(db)
        logger.info(
            "heuristic accuracy: %s over %d epochs (%s nights)",
            result.get("accuracy"),
            result.get("paired_epochs", 0),
            result.get("nights", 0),
        )
        for actual, predictions in sorted(result.get("confusion", {}).items()):
            total = sum(predictions.values())
            detail = ", ".join(
                f"{stage} {count}" for stage, count in sorted(predictions.items())
            )
            logger.info("  actual %-6s (%3d): %s", actual, total, detail)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
