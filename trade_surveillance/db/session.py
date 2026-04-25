from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from trade_surveillance.db.migrator import get_engine


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db_session() -> Generator[Session, None, None]:
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
