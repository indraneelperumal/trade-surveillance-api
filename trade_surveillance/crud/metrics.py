from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.alert import Alert
from trade_surveillance.models.trade import Trade
from trade_surveillance.schemas.metrics import OverviewMetricsRead, SymbolAlertCount


def _norm_status_key(raw: str | None) -> str:
    if not raw:
        return "unknown"
    s = raw.strip().upper().replace("-", "_")
    if s == "OPEN":
        return "open"
    if s == "CLOSED":
        return "closed"
    if s in ("IN_PROGRESS", "INPROGRESS"):
        return "in-progress"
    return raw.strip().lower()


def _norm_severity_key(raw: str | None) -> str:
    if not raw:
        return "none"
    s = raw.strip().upper()
    if s == "HIGH":
        return "high"
    if s == "MEDIUM":
        return "med"
    if s == "LOW":
        return "low"
    if s == "NONE":
        return "none"
    return raw.strip().lower()


def get_overview_metrics(db: Session) -> OverviewMetricsRead:
    total_alerts = int(db.scalar(select(func.count()).select_from(Alert)) or 0)
    total_trades = int(db.scalar(select(func.count()).select_from(Trade)) or 0)

    status_rows = db.execute(select(Alert.status, func.count()).group_by(Alert.status)).all()
    alerts_by_status: dict[str, int] = defaultdict(int)
    for st, cnt in status_rows:
        alerts_by_status[_norm_status_key(st)] += int(cnt)

    sev_rows = db.execute(select(Alert.severity, func.count()).group_by(Alert.severity)).all()
    alerts_by_severity: dict[str, int] = defaultdict(int)
    for sev, cnt in sev_rows:
        alerts_by_severity[_norm_severity_key(sev)] += int(cnt)

    type_rows = db.execute(select(Alert.anomaly_type, func.count()).group_by(Alert.anomaly_type)).all()
    alerts_by_anomaly_type: dict[str, int] = defaultdict(int)
    for atype, cnt in type_rows:
        key = (atype or "unknown").strip()
        alerts_by_anomaly_type[key] += int(cnt)

    open_sev_rows = db.execute(
        select(Alert.severity, func.count())
        .where(func.upper(Alert.status) == "OPEN")
        .group_by(Alert.severity)
    ).all()
    open_alerts_by_severity: dict[str, int] = defaultdict(int)
    for sev, cnt in open_sev_rows:
        open_alerts_by_severity[_norm_severity_key(sev)] += int(cnt)

    open_high = int(
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(func.upper(Alert.status) == "OPEN", func.upper(Alert.severity) == "HIGH")
        )
        or 0
    )

    sym_stmt = (
        select(Trade.symbol, func.count(Alert.id))
        .join(Alert, Alert.trade_id == Trade.trade_id)
        .group_by(Trade.symbol)
        .order_by(func.count(Alert.id).desc())
        .limit(10)
    )
    sym_rows = db.execute(sym_stmt).all()
    top_symbols = [SymbolAlertCount(symbol=row[0], count=int(row[1])) for row in sym_rows]

    return OverviewMetricsRead(
        total_alerts=total_alerts,
        total_trades=total_trades,
        alerts_by_status=dict(alerts_by_status),
        alerts_by_severity=dict(alerts_by_severity),
        alerts_by_anomaly_type=dict(alerts_by_anomaly_type),
        open_alerts_by_severity=dict(open_alerts_by_severity),
        open_high_severity_count=open_high,
        top_symbols_by_alerts=top_symbols,
    )
