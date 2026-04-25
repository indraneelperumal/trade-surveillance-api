from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlertCreate(BaseModel):
    trade_id: UUID
    anomaly_score: float | None = None
    anomaly_rank: int | None = None
    anomaly_type: str | None = None
    top_shap_feature: str | None = None
    top_3_shap_features: dict | None = None
    severity: str = "MEDIUM"
    status: str = "OPEN"
    disposition: str | None = None
    assigned_to: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None


class AlertUpdate(BaseModel):
    anomaly_score: float | None = None
    anomaly_rank: int | None = None
    anomaly_type: str | None = None
    top_shap_feature: str | None = None
    top_3_shap_features: dict | None = None
    severity: str | None = None
    status: str | None = None
    disposition: str | None = None
    assigned_to: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trade_id: UUID
    anomaly_score: float | None
    anomaly_rank: int | None
    anomaly_type: str | None
    top_shap_feature: str | None
    top_3_shap_features: dict | None
    severity: str
    status: str
    disposition: str | None
    assigned_to: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
