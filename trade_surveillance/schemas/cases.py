from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from trade_surveillance.schemas.alerts import AlertRead
from trade_surveillance.schemas.investigation_notes import InvestigationNoteRead
from trade_surveillance.schemas.trades import TradeRead


class AssigneeUser(BaseModel):
    id: UUID
    email: str
    display_name: str | None = None


class AlertCaseRead(AlertRead):
    """Alert with case workflow fields."""

    assignee_user: AssigneeUser | None = None
    age_hours: float = 0.0
    is_stale: bool = False


class TradeCaseRead(TradeRead):
    spread_bps: float | None = None
    relative_spread: float | None = None
    is_block_trade: bool = False
    trader_desk: str | None = None
    trader_region: str | None = None
    client_type: str | None = None
    client_mifid_category: str | None = None
    counterparty_name: str | None = None


class InvestigationRuleItem(BaseModel):
    rule_code: str
    label: str
    status: str = "triggered"
    detail: str | None = None


class InvestigationSection(BaseModel):
    id: str
    title: str
    body: str | None = None
    bullets: list[str] | None = None
    items: list[InvestigationRuleItem] | None = None
    emphasis: str = "default"


class InvestigationHeadline(BaseModel):
    verdict: str
    verdict_label: str
    verdict_hint: str | None = None
    confidence: str | None = None
    confidence_label: str | None = None
    model_version: str | None = None
    completed_at: datetime | None = None


class InvestigationPresentation(BaseModel):
    id: UUID
    alert_id: UUID
    review_status: str
    headline: InvestigationHeadline
    sections: list[InvestigationSection]
    error: str | None = None


class CasePermissions(BaseModel):
    can_assign: bool = False
    can_take: bool = False
    can_close: bool = False
    can_escalate: bool = False
    can_run_ai: bool = False
    can_approve_investigation: bool = False


class CaseBundleRead(BaseModel):
    alert: AlertCaseRead
    trade: TradeCaseRead | None = None
    investigation: InvestigationPresentation | None = None
    notes: list[InvestigationNoteRead] = Field(default_factory=list)
    permissions: CasePermissions


class AssignAlertRequest(BaseModel):
    assigned_to: UUID


class EscalateAlertRequest(BaseModel):
    note: str = Field(min_length=3)


class CloseAlertRequest(BaseModel):
    disposition: str
    note: str = Field(min_length=3)


class ApproveInvestigationRequest(BaseModel):
    override_note: str | None = None
