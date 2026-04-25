from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from trade_surveillance.models.base import Base


class Counterparty(Base):
    __tablename__ = "counterparties"

    counterparty_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(100))
    counterparty_lei: Mapped[str | None] = mapped_column(String(20))
    counterparty_type: Mapped[str | None] = mapped_column(String(30))
