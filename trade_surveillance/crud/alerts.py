from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.alert import Alert
from trade_surveillance.schemas.alerts import AlertCreate, AlertUpdate


def create_alert(db: Session, payload: AlertCreate) -> Alert:
    alert = Alert(**payload.model_dump(exclude_unset=True))
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def list_alerts(db: Session, offset: int = 0, limit: int = 50) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_alerts(db: Session) -> int:
    stmt = select(func.count()).select_from(Alert)
    return int(db.scalar(stmt) or 0)


def get_alert(db: Session, alert_id: UUID) -> Alert | None:
    return db.get(Alert, alert_id)


def update_alert(db: Session, alert: Alert, payload: AlertUpdate) -> Alert:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(alert, key, value)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def delete_alert(db: Session, alert: Alert) -> None:
    db.delete(alert)
    db.commit()
