from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.domain.enums import (
    ALERT_PENDING_OFFICER_REVIEW,
    OPEN_WORK_STATUSES,
    STALE_HOURS,
)
from trade_surveillance.models.alert import Alert
from trade_surveillance.models.trade import Trade
from trade_surveillance.models.user import User
from trade_surveillance.schemas.metrics import AssigneeOpenCount, OverviewMetricsRead, SymbolAlertCount


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
    if s == "PENDING_OFFICER_REVIEW":
        return "pending-officer-review"
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

    open_work = tuple(OPEN_WORK_STATUSES)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)

    open_unassigned_high = int(
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                func.upper(Alert.status).in_(open_work),
                func.upper(Alert.severity) == "HIGH",
                Alert.assigned_to.is_(None),
            )
        )
        or 0
    )

    pending_officer = int(
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(func.upper(Alert.status) == ALERT_PENDING_OFFICER_REVIEW)
        )
        or 0
    )

    stale_open = int(
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                func.upper(Alert.status).in_(open_work),
                Alert.updated_at < cutoff,
            )
        )
        or 0
    )

    assignee_rows = db.execute(
        select(User.id, User.email, User.display_name, func.count(Alert.id))
        .join(Alert, Alert.assigned_to == User.id)
        .where(func.upper(Alert.status).in_(open_work))
        .group_by(User.id, User.email, User.display_name)
        .order_by(func.count(Alert.id).desc())
        .limit(20)
    ).all()
    alerts_per_assignee = [
        AssigneeOpenCount(
            user_id=row[0],
            email=row[1],
            display_name=row[2],
            open_count=int(row[3]),
        )
        for row in assignee_rows
    ]

    return OverviewMetricsRead(
        total_alerts=total_alerts,
        total_trades=total_trades,
        alerts_by_status=dict(alerts_by_status),
        alerts_by_severity=dict(alerts_by_severity),
        alerts_by_anomaly_type=dict(alerts_by_anomaly_type),
        open_alerts_by_severity=dict(open_alerts_by_severity),
        open_high_severity_count=open_high,
        top_symbols_by_alerts=top_symbols,
        open_unassigned_high=open_unassigned_high,
        pending_officer_review=pending_officer,
        stale_open_24h=stale_open,
        sla_breach_count=stale_open,
        alerts_per_assignee=alerts_per_assignee,
    )
