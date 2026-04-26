from __future__ import annotations

from sqlalchemy.engine import Engine

from trade_surveillance.models.base import Base
from trade_surveillance.models.user import User
from trade_surveillance.models.instrument import Instrument
from trade_surveillance.models.trader import Trader
from trade_surveillance.models.client import Client
from trade_surveillance.models.counterparty import Counterparty
from trade_surveillance.models.trade import Trade
from trade_surveillance.models.alert import Alert
from trade_surveillance.models.investigation import Investigation
from trade_surveillance.models.investigation_note import InvestigationNote
from trade_surveillance.models.model_run import ModelRun
from trade_surveillance.models.system_config import SystemConfig

__all__ = [
    "Base",
    "User",
    "Instrument",
    "Trader",
    "Client",
    "Counterparty",
    "Trade",
    "Alert",
    "Investigation",
    "InvestigationNote",
    "ModelRun",
    "SystemConfig",
    "create_tables",
]


def create_tables(engine: Engine) -> None:
    """
    Creates all tables discovered in SQLAlchemy metadata.
    Order matters for foreign keys — users first, then reference tables,
    then trades, then workflow tables.
    """
    Base.metadata.create_all(bind=engine)
