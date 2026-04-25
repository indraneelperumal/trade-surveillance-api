from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.investigation_note import InvestigationNote
from trade_surveillance.schemas.investigation_notes import (
    InvestigationNoteCreate,
    InvestigationNoteUpdate,
)


def create_investigation_note(
    db: Session,
    payload: InvestigationNoteCreate,
) -> InvestigationNote:
    note = InvestigationNote(**payload.model_dump(exclude_unset=True))
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def list_investigation_notes(
    db: Session,
    offset: int = 0,
    limit: int = 100,
    alert_id: UUID | None = None,
    investigation_id: UUID | None = None,
) -> list[InvestigationNote]:
    stmt = select(InvestigationNote).order_by(InvestigationNote.created_at.desc())
    if alert_id:
        stmt = stmt.where(InvestigationNote.alert_id == alert_id)
    if investigation_id:
        stmt = stmt.where(InvestigationNote.investigation_id == investigation_id)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_investigation_notes(
    db: Session,
    alert_id: UUID | None = None,
    investigation_id: UUID | None = None,
) -> int:
    stmt = select(func.count()).select_from(InvestigationNote)
    if alert_id:
        stmt = stmt.where(InvestigationNote.alert_id == alert_id)
    if investigation_id:
        stmt = stmt.where(InvestigationNote.investigation_id == investigation_id)
    return int(db.scalar(stmt) or 0)


def get_investigation_note(db: Session, note_id: UUID) -> InvestigationNote | None:
    return db.get(InvestigationNote, note_id)


def update_investigation_note(
    db: Session,
    note: InvestigationNote,
    payload: InvestigationNoteUpdate,
) -> InvestigationNote:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(note, key, value)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def delete_investigation_note(db: Session, note: InvestigationNote) -> None:
    db.delete(note)
    db.commit()
