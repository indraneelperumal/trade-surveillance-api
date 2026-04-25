from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_surveillance.models.trade import Trade
from trade_surveillance.schemas.trades import TradeCreate, TradeUpdate


def create_trade(db: Session, payload: TradeCreate) -> Trade:
    trade = Trade(**payload.model_dump(exclude_unset=True))
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def list_trades(
    db: Session,
    offset: int = 0,
    limit: int = 50,
    symbol: str | None = None,
) -> list[Trade]:
    stmt = select(Trade).order_by(Trade.timestamp.desc())
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_trades(db: Session, symbol: str | None = None) -> int:
    stmt = select(func.count()).select_from(Trade)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    return int(db.scalar(stmt) or 0)


def get_trade(db: Session, trade_id: UUID) -> Trade | None:
    return db.get(Trade, trade_id)


def update_trade(db: Session, trade: Trade, payload: TradeUpdate) -> Trade:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(trade, key, value)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def delete_trade(db: Session, trade: Trade) -> None:
    db.delete(trade)
    db.commit()
