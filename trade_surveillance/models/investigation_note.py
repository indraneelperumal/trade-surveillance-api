from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from trade_surveillance.models.base import Base


class InvestigationNote(Base):
    """
    Audit trail notes for investigations and alerts.
    Captures all actions, comments, and status changes.
    """

    __tablename__ = "investigation_notes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    alert_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alerts.id")
    )
    investigation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("investigations.id")
    )

    note_type: Mapped[str] = mapped_column(String(30), default="COMMENT")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    author_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    is_system: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_investigation_notes_alert_id", "alert_id"),
        Index("ix_investigation_notes_investigation_id", "investigation_id"),
        Index("ix_investigation_notes_created_at", "created_at"),
    )
