from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.investigation import Investigation
from trade_surveillance.schemas.investigations import InvestigationCreate, InvestigationUpdate


def create_investigation(db: Session, payload: InvestigationCreate) -> Investigation:
    record = Investigation(**payload.model_dump(exclude_unset=True))
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_investigations(
    db: Session,
    offset: int = 0,
    limit: int = 50,
    alert_id: UUID | None = None,
) -> list[Investigation]:
    stmt = select(Investigation).order_by(Investigation.created_at.desc())
    if alert_id:
        stmt = stmt.where(Investigation.alert_id == alert_id)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_investigations(db: Session, alert_id: UUID | None = None) -> int:
    stmt = select(func.count()).select_from(Investigation)
    if alert_id:
        stmt = stmt.where(Investigation.alert_id == alert_id)
    return int(db.scalar(stmt) or 0)


def get_investigation(db: Session, investigation_id: UUID) -> Investigation | None:
    return db.get(Investigation, investigation_id)


def update_investigation(
    db: Session,
    record: Investigation,
    payload: InvestigationUpdate,
) -> Investigation:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(record, key, value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_investigation(db: Session, record: Investigation) -> None:
    db.delete(record)
    db.commit()
