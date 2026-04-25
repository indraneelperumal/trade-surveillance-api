from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Float, BigInteger, Boolean, Date, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from trade_surveillance.models.base import Base


class Trade(Base):
    __tablename__ = "trades"

    trade_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    trade_time_ns: Mapped[int | None] = mapped_column(BigInteger)

    symbol: Mapped[str] = mapped_column(String(20), ForeignKey("instruments.symbol"), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(5), default="USD")

    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trade_value: Mapped[float | None] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str | None] = mapped_column(String(20))
    liquidity_flag: Mapped[str | None] = mapped_column(String(5))
    trade_condition: Mapped[str | None] = mapped_column(String(10))

    bid_price: Mapped[float | None] = mapped_column(Float)
    ask_price: Mapped[float | None] = mapped_column(Float)
    bid_size: Mapped[int | None] = mapped_column(BigInteger)
    ask_size: Mapped[int | None] = mapped_column(BigInteger)

    trader_id: Mapped[str] = mapped_column(String(20), ForeignKey("traders.trader_id"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(20), ForeignKey("clients.client_id"), nullable=False)

    mid_price: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    spread_bps: Mapped[float | None] = mapped_column(Float)
    relative_spread: Mapped[float | None] = mapped_column(Float)
    nbbo_bid: Mapped[float | None] = mapped_column(Float)
    nbbo_ask: Mapped[float | None] = mapped_column(Float)
    nbbo_mid: Mapped[float | None] = mapped_column(Float)
    price_vs_nbbo_bps: Mapped[float | None] = mapped_column(Float)
    adv_pct: Mapped[float | None] = mapped_column(Float)
    is_block_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    is_off_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    is_otc: Mapped[bool] = mapped_column(Boolean, default=False)
    trade_date: Mapped[datetime | None] = mapped_column(Date)
    settlement_date: Mapped[datetime | None] = mapped_column(Date)

    isin: Mapped[str | None] = mapped_column(String(12))
    cusip: Mapped[str | None] = mapped_column(String(9))
    sector: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    asset_class: Mapped[str | None] = mapped_column(String(20))
    market_cap: Mapped[str | None] = mapped_column(String(20))

    trader_desk: Mapped[str | None] = mapped_column(String(50))
    trader_book: Mapped[str | None] = mapped_column(String(20))
    trader_region: Mapped[str | None] = mapped_column(String(20))
    trader_type: Mapped[str | None] = mapped_column(String(30))
    risk_limit_usd: Mapped[int | None] = mapped_column(BigInteger)

    client_type: Mapped[str | None] = mapped_column(String(30))
    client_lei: Mapped[str | None] = mapped_column(String(20))
    client_domicile: Mapped[str | None] = mapped_column(String(10))
    client_mifid_category: Mapped[str | None] = mapped_column(String(30))
    aum_tier: Mapped[str | None] = mapped_column(String(20))

    counterparty_id: Mapped[str | None] = mapped_column(String(20), ForeignKey("counterparties.counterparty_id"))
    counterparty_name: Mapped[str | None] = mapped_column(String(100))
    counterparty_lei: Mapped[str | None] = mapped_column(String(20))
    counterparty_type: Mapped[str | None] = mapped_column(String(30))

    algo_strategy: Mapped[str | None] = mapped_column(String(30))
    algo_used: Mapped[bool] = mapped_column(Boolean, default=False)
    order_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    parent_order_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

    mifid_capacity: Mapped[str | None] = mapped_column(String(10))
    short_sell_flag: Mapped[str | None] = mapped_column(String(10))

    commission_bps: Mapped[float | None] = mapped_column(Float)
    commission_usd: Mapped[float | None] = mapped_column(Float)
    market_impact_bps: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_trades_symbol_timestamp", "symbol", "timestamp"),
        Index("ix_trades_trader_id", "trader_id"),
        Index("ix_trades_client_id", "client_id"),
        Index("ix_trades_trade_date", "trade_date"),
    )
