from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from trade_surveillance.domain.enums import (
    ALERT_PENDING_OFFICER_REVIEW,
    OPEN_WORK_STATUSES,
    STALE_HOURS,
)

from trade_surveillance.models.alert import Alert
from trade_surveillance.models.trade import Trade
from trade_surveillance.models.user import User
from trade_surveillance.schemas.alerts import AlertCreate, AlertRead, AlertUpdate


def _normalize_create_payload(payload: AlertCreate) -> dict:
    data = payload.model_dump()
    if isinstance(data.get("status"), str):
        s = data["status"].strip().lower().replace("-", "_")
        sm = {
            "open": "OPEN",
            "closed": "CLOSED",
            "in_progress": "IN_PROGRESS",
            "pending_officer_review": ALERT_PENDING_OFFICER_REVIEW,
        }
        if s in sm:
            data["status"] = sm[s]
    if isinstance(data.get("severity"), str):
        sev = data["severity"].strip().upper()
        sevm = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "NONE": "NONE", "MED": "MEDIUM"}
        if sev in sevm:
            data["severity"] = sevm[sev]
    return data


def _alert_base_stmt():
    return (
        select(Alert, Trade.symbol, Trade.exchange, Trade.trader_id, User.email)
        .join(Trade, Trade.trade_id == Alert.trade_id)
        .outerjoin(User, User.id == Alert.assigned_to)
    )


def _row_to_alert_read(
    alert: Alert,
    symbol: str | None,
    exchange: str | None,
    trader_id: str | None,
    assignee_email: str | None,
) -> AlertRead:
    return AlertRead(
        id=alert.id,
        trade_id=alert.trade_id,
        anomaly_score=alert.anomaly_score,
        anomaly_rank=alert.anomaly_rank,
        anomaly_type=alert.anomaly_type,
        top_shap_feature=alert.top_shap_feature,
        top_3_shap_features=alert.top_3_shap_features,
        feature_spec_version=alert.feature_spec_version,
        model_features=alert.model_features,
        scoring_model_run_id=alert.scoring_model_run_id,
        scored_at=alert.scored_at,
        scoring_mode=alert.scoring_mode,
        severity=alert.severity,
        status=alert.status,
        disposition=alert.disposition,
        assigned_to=alert.assigned_to,
        reviewed_by=alert.reviewed_by,
        reviewed_at=alert.reviewed_at,
        notes=alert.notes,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
        symbol=symbol,
        exchange=exchange,
        trader_id=trader_id,
        assignee=assignee_email,
    )


def _apply_list_filters(
    stmt,
    *,
    status: str | None,
    severity: str | None,
    symbol: str | None,
    anomaly_type: str | None,
    assigned_to: UUID | None = None,
    unassigned: bool = False,
    stale: bool = False,
    exclude_closed: bool = False,
):
    if exclude_closed:
        stmt = stmt.where(func.upper(Alert.status) != "CLOSED")
    if status:
        s = status.strip().lower().replace("-", "_")
        if s == "open":
            stmt = stmt.where(func.upper(Alert.status) == "OPEN")
        elif s == "closed":
            stmt = stmt.where(func.upper(Alert.status) == "CLOSED")
        elif s == "in_progress":
            stmt = stmt.where(
                or_(
                    func.upper(Alert.status) == "IN_PROGRESS",
                    func.upper(Alert.status) == "IN-PROGRESS",
                )
            )
        elif s in ("pending_officer_review", "pending_officer"):
            stmt = stmt.where(func.upper(Alert.status) == ALERT_PENDING_OFFICER_REVIEW)
    if assigned_to:
        stmt = stmt.where(Alert.assigned_to == assigned_to)
    if unassigned:
        stmt = stmt.where(Alert.assigned_to.is_(None))
    if stale:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)
        stmt = stmt.where(
            func.upper(Alert.status).in_(tuple(OPEN_WORK_STATUSES)),
            Alert.updated_at < cutoff,
        )
    if severity:
        sev = severity.strip().lower()
        sev_map = {
            "high": "HIGH",
            "med": "MEDIUM",
            "medium": "MEDIUM",
            "low": "LOW",
            "none": "NONE",
        }
        if sev in sev_map:
            stmt = stmt.where(func.upper(Alert.severity) == sev_map[sev])
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.strip().upper())
    if anomaly_type:
        stmt = stmt.where(Alert.anomaly_type == anomaly_type)
    return stmt


def create_alert(db: Session, payload: AlertCreate) -> AlertRead:
    data = _normalize_create_payload(payload)
    alert = Alert(**data)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    read = get_alert_read(db, alert.id)
    assert read is not None
    return read


def list_alerts(
    db: Session,
    offset: int = 0,
    limit: int = 50,
    *,
    status: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    anomaly_type: str | None = None,
    assigned_to: UUID | None = None,
    unassigned: bool = False,
    stale: bool = False,
    exclude_closed: bool = False,
) -> list[AlertRead]:
    stmt = _alert_base_stmt()
    stmt = _apply_list_filters(
        stmt,
        status=status,
        severity=severity,
        symbol=symbol,
        anomaly_type=anomaly_type,
        assigned_to=assigned_to,
        unassigned=unassigned,
        stale=stale,
        exclude_closed=exclude_closed,
    )
    stmt = stmt.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    rows = db.execute(stmt).all()
    return [_row_to_alert_read(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def count_alerts(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    anomaly_type: str | None = None,
    assigned_to: UUID | None = None,
    unassigned: bool = False,
    stale: bool = False,
    exclude_closed: bool = False,
) -> int:
    stmt = select(func.count()).select_from(Alert).join(Trade, Trade.trade_id == Alert.trade_id)
    stmt = _apply_list_filters(
        stmt,
        status=status,
        severity=severity,
        symbol=symbol,
        anomaly_type=anomaly_type,
        assigned_to=assigned_to,
        unassigned=unassigned,
        stale=stale,
        exclude_closed=exclude_closed,
    )
    return int(db.scalar(stmt) or 0)


def get_alert(db: Session, alert_id: UUID) -> Alert | None:
    return db.get(Alert, alert_id)


def get_alert_read(db: Session, alert_id: UUID) -> AlertRead | None:
    stmt = _alert_base_stmt().where(Alert.id == alert_id)
    row = db.execute(stmt).first()
    if not row:
        return None
    return _row_to_alert_read(row[0], row[1], row[2], row[3], row[4])


def update_alert(db: Session, alert: Alert, payload: AlertUpdate) -> AlertRead:
    updates = payload.model_dump(exclude_unset=True)
    if "assignee" in updates:
        assignee_email = (updates.pop("assignee") or "").strip() or None
        if assignee_email:
            user = db.scalars(select(User).where(User.email == assignee_email)).first()
            alert.assigned_to = user.id if user else None
        else:
            alert.assigned_to = None
    for key, value in updates.items():
        setattr(alert, key, value)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    read = get_alert_read(db, alert.id)
    assert read is not None
    return read


def delete_alert(db: Session, alert: Alert) -> None:
    db.delete(alert)
    db.commit()


def set_alert_status(db: Session, alert: Alert, status: str) -> None:
    """Internal status transition (e.g. queue AI investigation)."""
    alert.status = status
    db.add(alert)
    db.commit()
