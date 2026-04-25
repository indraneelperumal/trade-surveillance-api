from __future__ import annotations

from sqlalchemy import String, Float, BigInteger
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from trade_surveillance.models.base import Base


class Trader(Base):
    __tablename__ = "traders"

    trader_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    trader_desk: Mapped[str | None] = mapped_column(String(50))
    trader_book: Mapped[str | None] = mapped_column(String(20))
    trader_region: Mapped[str | None] = mapped_column(String(20))
    trader_type: Mapped[str | None] = mapped_column(String(30))
    risk_limit_usd: Mapped[int | None] = mapped_column(BigInteger)
    preferred_symbols: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    off_hours_tendency: Mapped[float | None] = mapped_column(Float)
    avg_order_size: Mapped[str | None] = mapped_column(String(20))
    buy_side_bias: Mapped[float | None] = mapped_column(Float)
