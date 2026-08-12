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
        )
        predictions = {e["t"]: e["stage"] for e in stage_epochs(epochs)}
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pair ring features with cloud labels.")
    parser.add_argument("--csv", help="Write the dataset to this path.")
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
