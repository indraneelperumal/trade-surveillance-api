from __future__ import annotations

from pydantic import BaseModel


class SymbolAlertCount(BaseModel):
    symbol: str
    count: int


class OverviewMetricsRead(BaseModel):
    total_alerts: int
    total_trades: int
    alerts_by_status: dict[str, int]
    alerts_by_severity: dict[str, int]
    alerts_by_anomaly_type: dict[str, int]
    open_alerts_by_severity: dict[str, int]
    open_high_severity_count: int
    top_symbols_by_alerts: list[SymbolAlertCount]
