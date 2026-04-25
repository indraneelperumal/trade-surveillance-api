from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from trade_surveillance.models.base import Base


class Investigation(Base):
    """
    An investigation record for an alert.
    Contains the AI-generated or manual investigation results.
    """

    __tablename__ = "investigations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=False
    )

    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(10))
    rule_violated: Mapped[str | None] = mapped_column(String(50))

    summary: Mapped[str | None] = mapped_column(Text)
    evidence_points: Mapped[list | None] = mapped_column(JSONB)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    data_gaps: Mapped[str | None] = mapped_column(Text)

    memo_json: Mapped[dict | None] = mapped_column(JSONB)
    memo_storage_key: Mapped[str | None] = mapped_column(String(255))

    initiated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    is_auto: Mapped[bool] = mapped_column(default=True)

    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_investigations_alert_id", "alert_id"),
        Index("ix_investigations_verdict", "verdict"),
        Index("ix_investigations_created_at", "created_at"),
    )
