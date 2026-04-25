from __future__ import annotations

from sqlalchemy import String, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from trade_surveillance.models.base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12))
    cusip: Mapped[str | None] = mapped_column(String(9))
    sector: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    asset_class: Mapped[str] = mapped_column(String(20), default="Equity")
    market_cap: Mapped[str | None] = mapped_column(String(20))
    base_price: Mapped[float | None] = mapped_column(Float)
    ann_vol: Mapped[float | None] = mapped_column(Float)
    avg_spread_bps: Mapped[float | None] = mapped_column(Float)
    avg_daily_vol: Mapped[int | None] = mapped_column(BigInteger)
