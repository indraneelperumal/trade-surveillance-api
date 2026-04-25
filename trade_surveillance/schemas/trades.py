from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TradeCreate(BaseModel):
    trade_id: UUID
    timestamp: datetime
    symbol: str
    exchange: str | None = None
    currency: str = "USD"
    price: float
    volume: int
    side: str
    order_type: str | None = None
    client_id: str
    trader_id: str
    trade_value: float | None = None
    is_off_hours: bool = False
    is_otc: bool = False
    trade_date: date | None = None
    settlement_date: date | None = None


class TradeUpdate(BaseModel):
    exchange: str | None = None
    currency: str | None = None
    price: float | None = None
    volume: int | None = None
    side: str | None = None
    order_type: str | None = None
    trade_value: float | None = None
    is_off_hours: bool | None = None
    is_otc: bool | None = None
    trade_date: date | None = None
    settlement_date: date | None = None


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: UUID
    timestamp: datetime
    symbol: str
    exchange: str | None
    currency: str
    price: float
    volume: int
    trade_value: float | None
    side: str
    order_type: str | None
    client_id: str
    trader_id: str
    is_off_hours: bool
    is_otc: bool
    trade_date: date | None
    settlement_date: date | None
