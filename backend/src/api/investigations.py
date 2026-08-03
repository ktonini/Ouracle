"""CRUD endpoints for Saved Investigations (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SavedInvestigation


router = APIRouter(prefix="/api/investigations", tags=["investigations"])


class InvestigationCreate(BaseModel):
    name: str = Field(default="Untitled investigation", max_length=200)
    kind: str = Field(default="correlation")  # correlation | anomaly | ai | chart
    payload: Optional[Dict[str, Any]] = None


class InvestigationUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class InvestigationResponse(BaseModel):
    id: str
    name: str
    kind: str
    created_at: datetime
    updated_at: datetime
    payload: Optional[Dict[str, Any]] = None


def _to_response(inv: SavedInvestigation) -> InvestigationResponse:
    return InvestigationResponse(
        id=inv.id,
        name=inv.name,
        kind=inv.kind,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        payload=inv.payload,
    )


@router.get("", response_model=List[InvestigationResponse])
def list_investigations(db: Session = Depends(get_db)) -> List[InvestigationResponse]:
    rows = (
        db.query(SavedInvestigation)
        .order_by(SavedInvestigation.updated_at.desc())
        .all()
    )
    return [_to_response(r) for r in rows]


@router.post("", response_model=InvestigationResponse, status_code=201)
def create_investigation(
    body: InvestigationCreate,
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    inv = SavedInvestigation(
        id=str(uuid.uuid4()),
        name=body.name,
        kind=body.kind,
        payload=body.payload or {},
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _to_response(inv)


@router.get("/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(investigation_id: str, db: Session = Depends(get_db)) -> InvestigationResponse:
    inv = db.get(SavedInvestigation, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return _to_response(inv)


@router.patch("/{investigation_id}", response_model=InvestigationResponse)
def update_investigation(
    investigation_id: str,
    body: InvestigationUpdate,
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    inv = db.get(SavedInvestigation, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    if body.name is not None:
        inv.name = body.name
    if body.kind is not None:
        inv.kind = body.kind
    if body.payload is not None:
        inv.payload = body.payload
    db.commit()
    db.refresh(inv)
    return _to_response(inv)


@router.delete("/{investigation_id}", status_code=204, response_class=Response)
def delete_investigation(investigation_id: str, db: Session = Depends(get_db)) -> Response:
    # Annotate the Response return type so FastAPI does not infer a response
    # model for a 204, which it rejects at import time.
    inv = db.get(SavedInvestigation, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    db.delete(inv)
    db.commit()
    return Response(status_code=204)
