from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from trade_surveillance.config import get_settings
from trade_surveillance.models import create_tables

# Supabase / PgBouncer "Transaction" pooler (port 6543) cannot reuse server-side
# prepared statements across clients; psycopg must not prepare.
_TRANSACTION_POOLER_PORT = 6543


def _connect_args_for_url(db_url: str) -> dict:
    parsed = urlparse(db_url)
    if parsed.port == _TRANSACTION_POOLER_PORT:
        return {"prepare_threshold": None}
    return {}


def create_engine_from_url(db_url: str) -> Engine:
    connect_args = _connect_args_for_url(db_url)
    return create_engine(db_url, future=True, connect_args=connect_args)


def get_engine() -> Engine:
    settings = get_settings()
    db_url = settings.database_url
    if not db_url:
        raise ValueError("Set DATABASE_URL in your environment.")
    return create_engine_from_url(db_url)


def add_column(conn: Connection, table_name: str, column_sql: str) -> None:
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


def drop_column(conn: Connection, table_name: str, column_name: str) -> None:
    conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}"))


def rename_column(conn: Connection, table_name: str, old_name: str, new_name: str) -> None:
    conn.execute(text(f"ALTER TABLE {table_name} RENAME COLUMN {old_name} TO {new_name}"))


def run_migrations(conn: Connection) -> None:
    """
    Keep this function simple and explicit.
    Add schema changes here with helper functions, for example:

    add_column(conn, "alerts", "reviewer text")
    drop_column(conn, "alerts", "old_field")
    rename_column(conn, "alerts", "old_name", "new_name")
    """


def create_tables_and_migrate() -> None:
    engine = get_engine()
    create_tables(engine)
    with engine.begin() as conn:
        run_migrations(conn)
