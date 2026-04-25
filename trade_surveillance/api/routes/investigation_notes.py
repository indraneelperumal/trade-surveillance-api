from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import investigation_notes as notes_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.investigation_notes import (
    InvestigationNoteCreate,
    InvestigationNoteRead,
    InvestigationNoteUpdate,
)

router = APIRouter(prefix="/investigation-notes")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=InvestigationNoteRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_investigation_note(
    payload: InvestigationNoteCreate,
    db: Session = Depends(get_db_session),
) -> InvestigationNoteRead:
    return notes_crud.create_investigation_note(db, payload)


@router.get("", response_model=PaginatedResponse[InvestigationNoteRead], responses=ERROR_RESPONSES)
def list_investigation_notes(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    alert_id: UUID | None = Query(default=None),
    investigation_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[InvestigationNoteRead]:
    items = notes_crud.list_investigation_notes(
        db,
        offset=offset,
        limit=limit,
        alert_id=alert_id,
        investigation_id=investigation_id,
    )
    total = notes_crud.count_investigation_notes(
        db,
        alert_id=alert_id,
        investigation_id=investigation_id,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{note_id}", response_model=InvestigationNoteRead, responses=ERROR_RESPONSES)
def get_investigation_note(note_id: UUID, db: Session = Depends(get_db_session)) -> InvestigationNoteRead:
    note = notes_crud.get_investigation_note(db, note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation note not found")
    return note


@router.patch("/{note_id}", response_model=InvestigationNoteRead, responses=ERROR_RESPONSES)
def update_investigation_note(
    note_id: UUID,
    payload: InvestigationNoteUpdate,
    db: Session = Depends(get_db_session),
) -> InvestigationNoteRead:
    note = notes_crud.get_investigation_note(db, note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation note not found")
    return notes_crud.update_investigation_note(db, note, payload)


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_investigation_note(note_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    note = notes_crud.get_investigation_note(db, note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation note not found")
    notes_crud.delete_investigation_note(db, note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
