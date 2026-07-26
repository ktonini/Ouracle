"""Curated auto-discovery of strong metric correlations over a date range."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from .correlation import compute_correlation
from .metric_catalog import METRIC_CATALOG
from .series import build_metric_series

# (x_metric, y_metric, lag_days, human-readable reason)
CANDIDATES: List[Tuple[str, str, int, str]] = [
    ("sleep_session.bedtime_start_minutes", "readiness.score", 1, "Later bedtime vs next-day readiness"),
    ("sleep_session.total_sleep_duration", "readiness.score", 1, "Sleep duration vs next-day readiness"),
    ("sleep_session.efficiency", "readiness.score", 1, "Sleep efficiency vs next-day readiness"),
    ("sleep_session.average_hrv", "readiness.score", 0, "HRV vs same-day readiness"),
    ("sleep_session.average_heart_rate", "readiness.score", 0, "Resting HR vs same-day readiness"),
    ("activity.steps", "sleep.score", 0, "Steps vs same-night sleep"),
    ("activity.steps", "readiness.score", 1, "Steps vs next-day readiness"),
    ("activity.sedentary_time", "sleep.score", 0, "Sedentary time vs sleep"),
    ("activity.active_calories", "sleep.score", 0, "Active calories vs sleep"),
    ("readiness.temperature_deviation", "sleep.score", 0, "Temperature deviation vs sleep"),
]


@dataclass
class InterestingCorrelation:
    x_metric: str
    y_metric: str
    x_label: str
    y_label: str
    lag_days: int
    coefficient: float
    sample_count: int
    reason: str
    interpretation: str
    score: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "x_metric": self.x_metric,
            "y_metric": self.y_metric,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "lag_days": self.lag_days,
            "coefficient": self.coefficient,
            "sample_count": self.sample_count,
            "reason": self.reason,
            "interpretation": self.interpretation,
            "score": round(self.score, 4),
        }


def _label(path: str) -> str:
    spec = METRIC_CATALOG.get(path)
    return spec.label if spec else path


def find_interesting_correlations(
    db: Session,
    start: date,
    end: date,
    *,
    limit: int = 6,
    min_abs: float = 0.25,
    min_samples: int = 21,
) -> List[InterestingCorrelation]:
    """Evaluate curated candidate pairs and return the strongest correlations."""

    found: List[InterestingCorrelation] = []
    for x_path, y_path, lag, reason in CANDIDATES:
        y_end = end + timedelta(days=max(lag, 0))
        try:
            x_series = build_metric_series(db, x_path, start, end)
            y_series = build_metric_series(db, y_path, start, y_end)
        except KeyError:
            continue

        result = compute_correlation(
            x_series,
            y_series,
            lag_days=lag,
            method="pearson",
            x_label=_label(x_path),
            y_label=_label(y_path),
        )
        if result.coefficient is None:
            continue
        if result.sample_count < min_samples:
            continue
        if abs(result.coefficient) < min_abs:
            continue
        if result.warning == "low_samples":
            continue

        score = abs(result.coefficient) * min(result.sample_count / 60, 1.0)
        found.append(
            InterestingCorrelation(
                x_metric=x_path,
                y_metric=y_path,
                x_label=_label(x_path),
                y_label=_label(y_path),
                lag_days=lag,
                coefficient=result.coefficient,
                sample_count=result.sample_count,
                reason=reason,
                interpretation=result.interpretation,
                score=score,
            )
        )

    found.sort(key=lambda r: r.score, reverse=True)
    return found[:limit]
