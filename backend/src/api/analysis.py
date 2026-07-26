"""HTTP surface for Phase 2 analysis services.

Endpoints are read-only and recomputable. Series, correlations, and anomalies
are derived from the local database on demand; results carry sample counts,
date ranges, and method labels so the UI can present full provenance.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..analysis import (
    METRIC_CATALOG,
    build_metric_series,
    compute_anomalies,
    compute_correlation,
)
from ..analysis.interesting_correlations import find_interesting_correlations
from ..database import get_db


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class MetricSpecResponse(BaseModel):
    path: str
    label: str
    unit: str
    domain: str
    preferred: Optional[str]
    description: str = ""


class SeriesPointResponse(BaseModel):
    day: str
    value: float


class MetricSeriesResponse(BaseModel):
    metric_path: str
    label: str
    unit: str
    date_range: List[str]
    sample_count: int
    missing_count: int
    points: List[SeriesPointResponse]


class CorrelationResponse(BaseModel):
    x_metric: str
    y_metric: str
    lag_days: int
    method: str
    coefficient: Optional[float]
    sample_count: int
    paired_dates: List[List[str]]
    warning: Optional[str]
    interpretation: str


class InterestingCorrelationResponse(BaseModel):
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


class AnomalyResponse(BaseModel):
    metric_path: str
    label: str
    unit: str
    day: str
    value: float
    baseline_median: float
    baseline_mad: float
    score: float
    direction: str
    severity: str
    baseline_window: int
    method: str
    note: str


@router.get("/catalog", response_model=List[MetricSpecResponse])
def get_catalog() -> List[MetricSpecResponse]:
    return [MetricSpecResponse(**s.to_dict()) for s in METRIC_CATALOG.values()]  # type: ignore[arg-type]


def _parse_range(start_date: Optional[date], end_date: Optional[date], default_days: int = 90) -> tuple[date, date]:
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=default_days - 1))
    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    return start, end


@router.get("/series", response_model=MetricSeriesResponse)
def get_series(
    metric: str = Query(..., description="Catalog metric path"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
) -> MetricSeriesResponse:
    start, end = _parse_range(start_date, end_date)
    try:
        series = build_metric_series(db, metric, start, end)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return MetricSeriesResponse(**series.to_response())  # type: ignore[arg-type]


@router.get("/correlate", response_model=CorrelationResponse)
def get_correlation(
    x_metric: str = Query(...),
    y_metric: str = Query(...),
    lag_days: int = Query(0, ge=-30, le=30),
    method: str = Query("pearson", pattern="^(pearson|spearman)$"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
) -> CorrelationResponse:
    start, end = _parse_range(start_date, end_date)
    try:
        x_series = build_metric_series(db, x_metric, start, end)
        y_series = build_metric_series(db, y_metric, start, end)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from ..analysis.metric_catalog import METRIC_CATALOG

    x_spec = METRIC_CATALOG.get(x_metric)
    y_spec = METRIC_CATALOG.get(y_metric)
    result = compute_correlation(
        x_series,
        y_series,
        lag_days=lag_days,
        method=method,
        x_label=x_spec.label if x_spec else x_metric,
        y_label=y_spec.label if y_spec else y_metric,
    )
    return CorrelationResponse(**result.to_dict())  # type: ignore[arg-type]


@router.get("/interesting-correlations", response_model=List[InterestingCorrelationResponse])
def get_interesting_correlations(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(6, ge=1, le=20),
    min_abs: float = Query(0.25, ge=0.0, le=1.0),
    min_samples: int = Query(21, ge=2, le=365),
    db: Session = Depends(get_db),
) -> List[InterestingCorrelationResponse]:
    start, end = _parse_range(start_date, end_date)
    results = find_interesting_correlations(
        db, start, end, limit=limit, min_abs=min_abs, min_samples=min_samples
    )
    return [InterestingCorrelationResponse(**r.to_dict()) for r in results]  # type: ignore[arg-type]


@router.get("/anomalies/{day}", response_model=List[AnomalyResponse])
def get_anomalies(
    day: date,
    metrics: Optional[List[str]] = Query(default=None),
    window_days: int = Query(1, ge=1, le=60),
    baseline_window: int = Query(28, ge=7, le=120),
    db: Session = Depends(get_db),
) -> List[AnomalyResponse]:
    results = compute_anomalies(
        db,
        day,
        metrics=metrics,
        baseline_window=baseline_window,
        window_days=window_days,
    )
    return [AnomalyResponse(**r.to_dict()) for r in results]  # type: ignore[arg-type]
