from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.domain.enums import DEMO_DISPLAY_NAMES, DEMO_USER_ROLES, ROLE_ANALYST
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


def get_user_by_supabase_uid(db: Session, supabase_uid: str) -> User | None:
    stmt = select(User).where(User.supabase_uid == supabase_uid)
    return db.scalars(stmt).one_or_none()


def ensure_app_user(db: Session, *, supabase_uid: str, email: str) -> User:
    """
    Provision or refresh the app user row for a Supabase Auth login.

    Creates ANALYST users on first login and re-activates inactive accounts so
    JWT auth succeeds after Supabase sign-in.
    """
    email_key = email.strip().lower()
    demo_role = DEMO_USER_ROLES.get(email_key)
    demo_name = DEMO_DISPLAY_NAMES.get(email_key)

    user = get_user_by_supabase_uid(db, supabase_uid)
    if user:
        changed = False
        if not user.is_active:
            user.is_active = True
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if demo_role and user.role != demo_role:
            user.role = demo_role
            changed = True
        if demo_name and user.display_name != demo_name:
            user.display_name = demo_name
            changed = True
        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    user = User(
        email=email,
        display_name=demo_name or (email.split("@")[0] if "@" in email else email),
        role=demo_role or ROLE_ANALYST,
        is_active=True,
        supabase_uid=supabase_uid,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()
