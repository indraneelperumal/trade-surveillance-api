from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.model_run import ModelRun
from trade_surveillance.schemas.model_runs import ModelRunCreate, ModelRunUpdate


def create_model_run(db: Session, payload: ModelRunCreate) -> ModelRun:
    model_run = ModelRun(**payload.model_dump(exclude_unset=True))
    db.add(model_run)
    db.commit()
    db.refresh(model_run)
    return model_run


def list_model_runs(
    db: Session,
    offset: int = 0,
    limit: int = 50,
) -> list[ModelRun]:
    stmt = select(ModelRun).order_by(ModelRun.started_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_model_runs(db: Session) -> int:
    stmt = select(func.count()).select_from(ModelRun)
    return int(db.scalar(stmt) or 0)


def get_model_run(db: Session, model_run_id: UUID) -> ModelRun | None:
    return db.get(ModelRun, model_run_id)


def update_model_run(db: Session, model_run: ModelRun, payload: ModelRunUpdate) -> ModelRun:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(model_run, key, value)
    db.add(model_run)
    db.commit()
    db.refresh(model_run)
    return model_run


def delete_model_run(db: Session, model_run: ModelRun) -> None:
    db.delete(model_run)
    db.commit()
