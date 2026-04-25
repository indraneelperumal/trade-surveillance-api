from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Float, BigInteger, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from trade_surveillance.models.base import Base


class ModelRun(Base):
    """
    Tracks ML model training and scoring runs.
    Records parameters, metrics, and artifacts.
    """

    __tablename__ = "model_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(20))

    status: Mapped[str] = mapped_column(String(20), default="STARTED")

    parameters: Mapped[dict | None] = mapped_column(JSONB)
    metrics: Mapped[dict | None] = mapped_column(JSONB)

    total_records: Mapped[int | None] = mapped_column(BigInteger)
    flagged_count: Mapped[int | None] = mapped_column(BigInteger)
    recall: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)

    artifact_keys: Mapped[dict | None] = mapped_column(JSONB)

    runtime_seconds: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(String(1000))

    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_model_runs_run_type", "run_type"),
        Index("ix_model_runs_status", "status"),
        Index("ix_model_runs_started_at", "started_at"),
    )
