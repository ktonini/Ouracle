"""Lag-aware Pearson/Spearman correlation between two metric series.

A positive ``lag_days`` means ``y`` is shifted forward by N days relative to
``x`` — i.e. we compare ``x`` on day D with ``y`` on day D+N. This is the
useful framing for Oura questions such as "does later bedtime affect
readiness tomorrow?" (lag = +1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import sqrt
from typing import Dict, List, Optional, Tuple

from .series import MetricSeries


_MIN_PAIRED_FOR_INTERPRETATION = 7
_MIN_PAIRED_WITH_WARNING = 14


@dataclass
class CorrelationResult:
    x_metric: str
    y_metric: str
    lag_days: int
    method: str
    coefficient: Optional[float]
    sample_count: int
    paired_dates: List[Tuple[date, date]] = field(default_factory=list)
    warning: Optional[str] = None
    interpretation: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "x_metric": self.x_metric,
            "y_metric": self.y_metric,
            "lag_days": self.lag_days,
            "method": self.method,
            "coefficient": self.coefficient,
            "sample_count": self.sample_count,
            "paired_dates": [[a.isoformat(), b.isoformat()] for a, b in self.paired_dates],
            "warning": self.warning,
            "interpretation": self.interpretation,
        }


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sqrt(sum((x - mx) ** 2 for x in xs))
    dy = sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _rank(values: List[float]) -> List[float]:
    # Average rank for ties; supports Spearman.
    indexed = sorted(enumerate(values), key=lambda kv: kv[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    return _pearson(_rank(xs), _rank(ys))


def _strength_word(abs_c: float) -> str:
    if abs_c < 0.1:
        return "negligible"
    if abs_c < 0.3:
        return "weak"
    if abs_c < 0.5:
        return "moderate"
    if abs_c < 0.7:
        return "strong"
    return "very strong"


def _lag_sentence(x_label: str, y_label: str, lag_days: int) -> str:
    if lag_days == 0:
        return f"Each point pairs {x_label} and {y_label} on the same calendar day."
    if lag_days == 1:
        return (
            f"Lag +1 day: each point pairs one day's {x_label} with the next day's {y_label} "
            f"(e.g. last night's sleep vs tomorrow's readiness)."
        )
    if lag_days > 1:
        return (
            f"Lag +{lag_days} days: {x_label} on day D is paired with {y_label} on day D+{lag_days}."
        )
    return (
        f"Lag {lag_days} days: {y_label} on day D is paired with {x_label} on day D+{abs(lag_days)}."
    )


def _direction_sentence(x_label: str, y_label: str, coef: float) -> str:
    if abs(coef) < 0.1:
        return (
            f"Over this window, {x_label} and {y_label} barely move together — "
            "day-to-day noise or other factors may dominate."
        )
    if coef > 0:
        return (
            f"When {x_label} is higher than your usual on a given day, {y_label} on the paired day "
            f"tends to be higher too; when {x_label} is lower, {y_label} tends to be lower."
        )
    return (
        f"When {x_label} is higher than your usual on a given day, {y_label} on the paired day "
        f"tends to be lower; when {x_label} is lower, {y_label} tends to be higher."
    )


def format_user_correlation_summary(
    x_label: str,
    y_label: str,
    coef: Optional[float],
    lag_days: int,
    n: int,
) -> Tuple[str, Optional[str]]:
    """Plain-language summary for UI; returns (text, warning)."""
    warning: Optional[str] = None
    if n < _MIN_PAIRED_FOR_INTERPRETATION:
        return ("Not enough paired days to describe this relationship reliably.", "low_samples")
    if n < _MIN_PAIRED_WITH_WARNING:
        warning = "fewer_than_14_paired_samples"
    if coef is None:
        return (
            f"{x_label} and {y_label} could not be compared (one series has no variation in this range).",
            warning,
        )

    strength = _strength_word(abs(coef))
    direction = _direction_sentence(x_label, y_label, coef)
    lag = _lag_sentence(x_label, y_label, lag_days)
    sign = "positive" if coef > 0 else "negative"
    text = (
        f"{direction} This is a {strength} {sign} correlation (r = {coef:.2f}) across {n} paired days. {lag}"
    )
    return text, warning


def _interpret(
    coef: Optional[float],
    n: int,
    *,
    x_label: str = "X",
    y_label: str = "Y",
    lag_days: int = 0,
) -> Tuple[str, Optional[str]]:
    return format_user_correlation_summary(x_label, y_label, coef, lag_days, n)


def compute_correlation(
    x_series: MetricSeries,
    y_series: MetricSeries,
    lag_days: int = 0,
    method: str = "pearson",
    *,
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
) -> CorrelationResult:
    """Correlate ``x_series`` with ``y_series`` shifted forward by ``lag_days``."""

    if method not in {"pearson", "spearman"}:
        raise ValueError(f"unknown method '{method}'")
    y_map = {p.day: p.value for p in y_series.points}
    xs: List[float] = []
    ys: List[float] = []
    pairs: List[Tuple[date, date]] = []
    for p in x_series.points:
        target_day = p.day + timedelta(days=lag_days)
        v = y_map.get(target_day)
        if v is None:
            continue
        xs.append(p.value)
        ys.append(v)
        pairs.append((p.day, target_day))

    coef = _pearson(xs, ys) if method == "pearson" else _spearman(xs, ys)
    xl = x_label or x_series.metric_path
    yl = y_label or y_series.metric_path
    interpretation, warning = _interpret(
        coef, len(xs), x_label=xl, y_label=yl, lag_days=lag_days,
    )
    return CorrelationResult(
        x_metric=x_series.metric_path,
        y_metric=y_series.metric_path,
        lag_days=lag_days,
        method=method,
        coefficient=None if coef is None else round(coef, 4),
        sample_count=len(xs),
        paired_dates=pairs,
        warning=warning,
        interpretation=interpretation,
    )
