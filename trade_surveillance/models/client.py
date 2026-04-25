from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from trade_surveillance.models.base import Base


class Client(Base):
    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_type: Mapped[str | None] = mapped_column(String(30))
    client_lei: Mapped[str | None] = mapped_column(String(20))
    client_domicile: Mapped[str | None] = mapped_column(String(10))
    client_mifid_category: Mapped[str | None] = mapped_column(String(30))
    aum_tier: Mapped[str | None] = mapped_column(String(20))
