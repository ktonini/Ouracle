"""HTTP surface for the Phase 1 insights read models.

All endpoints are read-only and recomputable; they never write to imported data.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..mobile_server_manager import mobile_server_manager
from ..models import Activity, Readiness, Sleep, SleepSession
from ..insights import (
    build_action_cards,
    build_baseline_bundle,
    build_contributor_summaries,
    build_daily_guidance,
    build_sync_freshness,
)

router = APIRouter(prefix="/api/insights", tags=["insights"])


class ContributorSummaryResponse(BaseModel):
    domain: str
    key: str
    label: str
    status: str
    value: Optional[int] = None
    unit: str
    explanation: str
    source_path: str


class ContributorBundleResponse(BaseModel):
    day: date
    sleep: List[ContributorSummaryResponse] = Field(default_factory=list)
    readiness: List[ContributorSummaryResponse] = Field(default_factory=list)
    activity: List[ContributorSummaryResponse] = Field(default_factory=list)


class BaselineDeltaResponse(BaseModel):
    metric: str
    label: str
    unit: str
    current: Optional[float] = None
    baseline_7d: Optional[float] = None
    baseline_14d: Optional[float] = None
    baseline_30d: Optional[float] = None
    delta_7d: Optional[float] = None
    delta_14d: Optional[float] = None
    delta_30d: Optional[float] = None
    direction: Optional[str] = None
    sample_count_7d: int = 0
    sample_count_14d: int = 0
    sample_count_30d: int = 0
    preferred: Optional[str] = None


class BaselineBundleResponse(BaseModel):
    day: date
    deltas: List[BaselineDeltaResponse] = Field(default_factory=list)


class ActionEvidenceResponse(BaseModel):
    metric: str
    value: Any = None
    day: Optional[str] = None
    source_path: str


class ActionCardResponse(BaseModel):
    id: str
    day: str
    severity: str
    category: str
    title: str
    reason: str
    recommendation: str
    evidence: List[ActionEvidenceResponse] = Field(default_factory=list)
    dismissible: bool = True


class DailyGuidanceResponse(BaseModel):
    day: str
    headline: str
    body: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class SyncFreshnessResponse(BaseModel):
    latest_day: Optional[str] = None
    expected_latest_day: Optional[str] = None
    last_ingest_at: Optional[str] = None
    last_export_request_at: Optional[str] = None
    status: str
    message: Optional[str] = None
    mobile_server_enabled: bool = False
    mobile_server_status: Optional[str] = None
    automation_status: Optional[str] = None
    next_run: Optional[str] = None
    days_behind: Optional[int] = None


def _resolve_day(db: Session, day: Optional[date]) -> date:
    if day is not None:
        return day
    candidates = [
        db.query(Sleep.day).order_by(Sleep.day.desc()).limit(1).scalar(),
        db.query(Activity.day).order_by(Activity.day.desc()).limit(1).scalar(),
        db.query(Readiness.day).order_by(Readiness.day.desc()).limit(1).scalar(),
        db.query(SleepSession.day).order_by(SleepSession.day.desc()).limit(1).scalar(),
    ]
    valid = [d for d in candidates if d is not None]
    if not valid:
        raise HTTPException(status_code=404, detail="No data ingested yet.")
    return max(valid)


@router.get("/contributors/{day}", response_model=ContributorBundleResponse)
def get_contributors(day: date, db: Session = Depends(get_db)) -> ContributorBundleResponse:
    sleep = db.query(Sleep).filter(Sleep.day == day).one_or_none()
    readiness = db.query(Readiness).filter(Readiness.day == day).one_or_none()
    activity = db.query(Activity).filter(Activity.day == day).one_or_none()

    return ContributorBundleResponse(
        day=day,
        sleep=[ContributorSummaryResponse(**c.to_dict())
               for c in build_contributor_summaries("sleep", sleep.contributors if sleep else None)],
        readiness=[ContributorSummaryResponse(**c.to_dict())
                   for c in build_contributor_summaries("readiness", readiness.contributors if readiness else None)],
        activity=[ContributorSummaryResponse(**c.to_dict())
                  for c in build_contributor_summaries("activity", activity.contributors if activity else None)],
    )


@router.get("/baselines/{day}", response_model=BaselineBundleResponse)
def get_baselines(day: date, db: Session = Depends(get_db)) -> BaselineBundleResponse:
    bundle = build_baseline_bundle(db, day)
    return BaselineBundleResponse(
        day=bundle.day,
        deltas=[BaselineDeltaResponse(**d.to_dict()) for d in bundle.deltas],
    )


@router.get("/action-cards/{day}", response_model=List[ActionCardResponse])
def get_action_cards(day: date, db: Session = Depends(get_db)) -> List[ActionCardResponse]:
    cards = build_action_cards(db, day)
    return [ActionCardResponse(**c.to_dict()) for c in cards]


@router.get("/guidance/{day}", response_model=DailyGuidanceResponse)
def get_guidance(day: date, db: Session = Depends(get_db)) -> DailyGuidanceResponse:
    g = build_daily_guidance(db, day)
    return DailyGuidanceResponse(**g.to_dict())


@router.get("/sync-freshness", response_model=SyncFreshnessResponse)
def get_sync_freshness(db: Session = Depends(get_db)) -> SyncFreshnessResponse:
    state = mobile_server_manager.reconcile()
    fresh = build_sync_freshness(db, state)
    return SyncFreshnessResponse(**fresh.to_dict())


@router.get("/today", response_model=Dict[str, Any])
def get_today(
    day: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """One-shot endpoint combining everything the Today view needs."""

    resolved = _resolve_day(db, day)
    state = mobile_server_manager.reconcile()
    return {
        "day": resolved.isoformat(),
        "contributors": get_contributors(resolved, db).model_dump(),
        "baselines": get_baselines(resolved, db).model_dump(),
        "action_cards": [c.model_dump() for c in get_action_cards(resolved, db)],
        "guidance": get_guidance(resolved, db).model_dump(),
        "sync_freshness": build_sync_freshness(db, state).to_dict(),
    }
