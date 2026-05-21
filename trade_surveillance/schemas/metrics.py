from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class SymbolAlertCount(BaseModel):
    symbol: str
    count: int


class AssigneeOpenCount(BaseModel):
    user_id: UUID
    email: str
    display_name: str | None = None
    open_count: int


class OverviewMetricsRead(BaseModel):
    total_alerts: int
    total_trades: int
    alerts_by_status: dict[str, int]
    alerts_by_severity: dict[str, int]
    alerts_by_anomaly_type: dict[str, int]
    open_alerts_by_severity: dict[str, int]
    open_high_severity_count: int
    top_symbols_by_alerts: list[SymbolAlertCount]
    open_unassigned_high: int = 0
    pending_officer_review: int = 0
    stale_open_24h: int = 0
    sla_breach_count: int = 0
    alerts_per_assignee: list[AssigneeOpenCount] = []
