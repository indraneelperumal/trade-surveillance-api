from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from trade_surveillance.models.base import Base


class User(Base):
    """
    Minimal user record for audit trails and assignment.
    Supabase Auth handles authentication; this stores app-level info.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30), default="ANALYST")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    supabase_uid: Mapped[str | None] = mapped_column(String(100), unique=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_role", "role"),
        Index("ix_users_supabase_uid", "supabase_uid"),
    )
