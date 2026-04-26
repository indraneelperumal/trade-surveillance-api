from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from trade_surveillance.config import get_settings
from trade_surveillance.models import create_tables


def _normalize_db_url(db_url: str) -> str:
    """
    Force SQLAlchemy to use psycopg (v3) driver.
    Accepts existing SQLAlchemy URLs and upgrades plain postgresql:// URLs.
    """
    normalized = db_url
    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    elif normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql+psycopg://", 1)

    # psycopg/libpq doesn't accept "pgbouncer" as a connection option.
    # Remove it if present so Supabase pooler URLs work unchanged.
    parts = urlsplit(normalized)
    query_pairs = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k != "pgbouncer"]
    clean_query = urlencode(query_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, parts.fragment))


def get_engine() -> Engine:
    settings = get_settings()
    db_url = settings.database_url
    if not db_url:
        raise ValueError("Set DATABASE_URL in your environment.")
    return create_engine(_normalize_db_url(db_url), future=True)


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
