from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InvestigationCreate(BaseModel):
    alert_id: UUID
    verdict: str
    confidence: str | None = None
    rule_violated: str | None = None
    summary: str | None = None
    evidence_points: list | None = None
    recommended_action: str | None = None
    data_gaps: str | None = None
    memo_json: dict | None = None
    memo_storage_key: str | None = None
    initiated_by: UUID | None = None
    is_auto: bool = True
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InvestigationUpdate(BaseModel):
    verdict: str | None = None
    confidence: str | None = None
    rule_violated: str | None = None
    summary: str | None = None
    evidence_points: list | None = None
    recommended_action: str | None = None
    data_gaps: str | None = None
    memo_json: dict | None = None
    memo_storage_key: str | None = None
    initiated_by: UUID | None = None
    is_auto: bool | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID
    verdict: str
    confidence: str | None
    rule_violated: str | None
    summary: str | None
    evidence_points: list | None
    recommended_action: str | None
    data_gaps: str | None
    memo_json: dict | None
    memo_storage_key: str | None
    initiated_by: UUID | None
    is_auto: bool
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
