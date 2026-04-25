from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.user import User
from trade_surveillance.schemas.users import UserCreate, UserUpdate


def create_user(db: Session, payload: UserCreate) -> User:
    user = User(**payload.model_dump(exclude_unset=True))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session, offset: int = 0, limit: int = 50) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_users(db: Session) -> int:
    stmt = select(func.count()).select_from(User)
    return int(db.scalar(stmt) or 0)


def get_user(db: Session, user_id: UUID) -> User | None:
    return db.get(User, user_id)


def update_user(db: Session, user: User, payload: UserUpdate) -> User:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(user, key, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()
