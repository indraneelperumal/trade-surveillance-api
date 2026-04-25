from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import investigations as investigations_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.investigations import (
    InvestigationCreate,
    InvestigationRead,
    InvestigationUpdate,
)

router = APIRouter(prefix="/investigations")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_investigation(
    payload: InvestigationCreate,
    db: Session = Depends(get_db_session),
) -> InvestigationRead:
    return investigations_crud.create_investigation(db, payload)


@router.get("", response_model=PaginatedResponse[InvestigationRead], responses=ERROR_RESPONSES)
def list_investigations(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    alert_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[InvestigationRead]:
    items = investigations_crud.list_investigations(
        db,
        offset=offset,
        limit=limit,
        alert_id=alert_id,
    )
    total = investigations_crud.count_investigations(db, alert_id=alert_id)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{investigation_id}", response_model=InvestigationRead, responses=ERROR_RESPONSES)
def get_investigation(investigation_id: UUID, db: Session = Depends(get_db_session)) -> InvestigationRead:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return record


@router.patch("/{investigation_id}", response_model=InvestigationRead, responses=ERROR_RESPONSES)
def update_investigation(
    investigation_id: UUID,
    payload: InvestigationUpdate,
    db: Session = Depends(get_db_session),
) -> InvestigationRead:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return investigations_crud.update_investigation(db, record, payload)


@router.delete(
    "/{investigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_investigation(investigation_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    investigations_crud.delete_investigation(db, record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
