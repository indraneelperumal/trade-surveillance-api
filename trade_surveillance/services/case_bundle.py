from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.crud import investigation_notes as notes_crud
from trade_surveillance.crud import investigations as investigations_crud
from trade_surveillance.crud import trades as trades_crud
from trade_surveillance.domain.enums import OPEN_WORK_STATUSES, STALE_HOURS
from trade_surveillance.models.alert import Alert
from trade_surveillance.models.client import Client
from trade_surveillance.models.counterparty import Counterparty
from trade_surveillance.models.trade import Trade
from trade_surveillance.models.trader import Trader
from trade_surveillance.models.user import User
from trade_surveillance.schemas.cases import (
    AlertCaseRead,
    AssigneeUser,
    CaseBundleRead,
    TradeCaseRead,
)
from trade_surveillance.schemas.investigation_notes import InvestigationNoteRead
from trade_surveillance.services.case_permissions import build_case_permissions
from trade_surveillance.services.investigation_presentation import (
    build_investigation_presentation,
)


def _age_hours(updated_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - updated_at).total_seconds() / 3600.0)


def _is_stale(alert: Alert) -> bool:
    status = (alert.status or "").upper()
    if status not in OPEN_WORK_STATUSES:
        return False
    return _age_hours(alert.updated_at) >= STALE_HOURS


def _assignee_user(db: Session, user_id: UUID | None) -> AssigneeUser | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user:
        return None
    return AssigneeUser(id=user.id, email=user.email, display_name=user.display_name)


def _trade_case_read(db: Session, trade_id: UUID) -> TradeCaseRead | None:
    trade = trades_crud.get_trade(db, trade_id)
    if not trade:
        return None

    trader = db.get(Trader, trade.trader_id)
    client = db.get(Client, trade.client_id)
    cp_name = trade.counterparty_name
    if not cp_name and trade.counterparty_id:
        cp = db.get(Counterparty, trade.counterparty_id)
        cp_name = cp.counterparty_name if cp else None

    return TradeCaseRead(
        trade_id=trade.trade_id,
        timestamp=trade.timestamp,
        symbol=trade.symbol,
        exchange=trade.exchange,
        currency=trade.currency,
        price=trade.price,
        volume=trade.volume,
        trade_value=trade.trade_value,
        side=trade.side,
        order_type=trade.order_type,
        client_id=trade.client_id,
        trader_id=trade.trader_id,
        is_off_hours=trade.is_off_hours,
        is_otc=trade.is_otc,
        trade_date=trade.trade_date,
        settlement_date=trade.settlement_date,
        spread_bps=trade.spread_bps,
        relative_spread=trade.relative_spread,
        is_block_trade=bool(trade.is_block_trade),
        trader_desk=trader.desk if trader else None,
        trader_region=trader.region if trader else None,
        client_type=client.client_type if client else None,
        client_mifid_category=client.client_mifid_category if client else None,
        counterparty_name=cp_name,
    )


def get_case_bundle(db: Session, alert_id: UUID, current_user: User) -> CaseBundleRead | None:
    base = alerts_crud.get_alert_read(db, alert_id)
    if not base:
        return None

    alert_row = alerts_crud.get_alert(db, alert_id)
    assert alert_row is not None

    assignee = _assignee_user(db, alert_row.assigned_to)
    age = _age_hours(alert_row.updated_at)

    alert_case = AlertCaseRead(
        **base.model_dump(),
        assignee_user=assignee,
        age_hours=round(age, 1),
        is_stale=_is_stale(alert_row),
    )

    trade = _trade_case_read(db, alert_row.trade_id)

    inv_list = investigations_crud.list_investigations(db, offset=0, limit=1, alert_id=alert_id)
    investigation_row = inv_list[0] if inv_list else None
    presentation = (
        build_investigation_presentation(investigation_row) if investigation_row else None
    )

    notes_raw = notes_crud.list_investigation_notes(db, offset=0, limit=100, alert_id=alert_id)
    notes = [InvestigationNoteRead.model_validate(n) for n in reversed(notes_raw)]

    permissions = build_case_permissions(current_user, alert_row, investigation_row)

    return CaseBundleRead(
        alert=alert_case,
        trade=trade,
        investigation=presentation,
        notes=notes,
        permissions=permissions,
    )
