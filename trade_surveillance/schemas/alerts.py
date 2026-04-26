from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


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
    feature_spec_version: str | None = None
    model_features: dict | None = None
    scoring_model_run_id: UUID | None = None
    scored_at: datetime | None = None
    scoring_mode: str | None = None


class AlertUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    anomaly_score: float | None = None
    anomaly_rank: int | None = None
    anomaly_type: str | None = None
    top_shap_feature: str | None = None
    top_3_shap_features: dict | None = None
    severity: str | None = None
    status: str | None = None
    disposition: str | None = None
    assigned_to: UUID | None = None
    assignee: str | None = Field(
        default=None,
        validation_alias=AliasChoices("assignee", "assignedTo"),
        description="User email; resolved to assigned_to in CRUD",
    )
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None
    feature_spec_version: str | None = None
    model_features: dict | None = None
    scoring_model_run_id: UUID | None = None
    scored_at: datetime | None = None
    scoring_mode: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_status(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "status" in out and out["status"] is not None and isinstance(out["status"], str):
            s = out["status"].strip().lower().replace("-", "_")
            mapping = {"open": "OPEN", "closed": "CLOSED", "in_progress": "IN_PROGRESS"}
            if s in mapping:
                out["status"] = mapping[s]
        if "severity" in out and out["severity"] is not None and isinstance(out["severity"], str):
            sev = out["severity"].strip().upper()
            sev_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "NONE": "NONE", "MED": "MEDIUM"}
            if sev in sev_map:
                out["severity"] = sev_map[sev]
        return out


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trade_id: UUID
    anomaly_score: float | None
    anomaly_rank: int | None
    anomaly_type: str | None
    top_shap_feature: str | None
    top_3_shap_features: dict | None
    feature_spec_version: str | None = None
    model_features: dict | None = None
    scoring_model_run_id: UUID | None = None
    scored_at: datetime | None = None
    scoring_mode: str | None = None
    severity: str
    status: str
    disposition: str | None
    assigned_to: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    symbol: str | None = None
    exchange: str | None = None
    trader_id: str | None = None
    assignee: str | None = Field(
        default=None,
        description="Assignee display (email) when joined from users",
    )
