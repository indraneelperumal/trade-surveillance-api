from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Float, Boolean, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from trade_surveillance.models.base import Base


class Alert(Base):
    """
    An alert is created when a trade is flagged by the anomaly model.
    Tracks status, severity, disposition, and assignment.
    """

    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    trade_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trades.trade_id"), nullable=False, unique=True
    )

    anomaly_score: Mapped[float | None] = mapped_column(Float)
    anomaly_rank: Mapped[int | None] = mapped_column()
    anomaly_type: Mapped[str | None] = mapped_column(String(30))
    top_shap_feature: Mapped[str | None] = mapped_column(String(50))
    top_3_shap_features: Mapped[dict | None] = mapped_column(JSONB)

    severity: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    disposition: Mapped[str | None] = mapped_column(String(20))

    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_anomaly_type", "anomaly_type"),
        Index("ix_alerts_assigned_to", "assigned_to"),
        Index("ix_alerts_created_at", "created_at"),
    )
