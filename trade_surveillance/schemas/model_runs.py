from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ModelRunCreate(BaseModel):
    run_type: str
    model_name: str
    model_version: str | None = None
    status: str = "STARTED"
    parameters: dict | None = None
    metrics: dict | None = None
    total_records: int | None = None
    flagged_count: int | None = None
    recall: float | None = None
    precision: float | None = None
    artifact_keys: dict | None = None
    runtime_seconds: float | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ModelRunUpdate(BaseModel):
    run_type: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    status: str | None = None
    parameters: dict | None = None
    metrics: dict | None = None
    total_records: int | None = None
    flagged_count: int | None = None
    recall: float | None = None
    precision: float | None = None
    artifact_keys: dict | None = None
    runtime_seconds: float | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ModelRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_type: str
    model_name: str
    model_version: str | None
    status: str
    parameters: dict | None
    metrics: dict | None
    total_records: int | None
    flagged_count: int | None
    recall: float | None
    precision: float | None
    artifact_keys: dict | None
    runtime_seconds: float | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
