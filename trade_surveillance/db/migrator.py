from __future__ import annotations

from functools import lru_cache
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


@lru_cache(maxsize=1)
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
    Idempotent DDL for existing databases. ``create_all`` creates new tables/columns
    on empty installs; these statements upgrade older Postgres (e.g. Supabase) safely.
    """
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS system_config (
                key VARCHAR(128) NOT NULL PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_system_config_updated_at "
            "ON system_config (updated_at)"
        )
    )

    # Phase 1 — ML lineage / scoring columns on alerts
    conn.execute(
        text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS feature_spec_version VARCHAR(64)"
        )
    )
    conn.execute(text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS model_features JSONB"))
    conn.execute(
        text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS scoring_model_run_id UUID "
            "REFERENCES model_runs (id)"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS scored_at TIMESTAMP WITH TIME ZONE"
        )
    )
    conn.execute(
        text("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS scoring_mode VARCHAR(32)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_alerts_scoring_model_run_id "
            "ON alerts (scoring_model_run_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_alerts_feature_spec_version "
            "ON alerts (feature_spec_version)"
        )
    )

    # Phase 2 — investigations schema hardening for agent output
    #
    # Showstopper: rule_violated was VARCHAR(50) which truncates Claude Sonnet
    # output (e.g. "VOLUME_SPIKE (abnormally large trade volume far outside
    # normal ranges…)" > 50 chars).  Widen to TEXT unconditionally.
    conn.execute(
        text(
            "ALTER TABLE investigations "
            "ALTER COLUMN rule_violated TYPE TEXT USING rule_violated::TEXT"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE investigations ADD COLUMN IF NOT EXISTS "
            "model_version VARCHAR(50)"
        )
    )
    conn.execute(
        text(
            "ALTER TABLE investigations ADD COLUMN IF NOT EXISTS "
            "error_message TEXT"
        )
    )


    # Phase 3 — alert close workflow
    #
    # alerts.disposition was VARCHAR(20) which is too short for
    # ESCALATED_TO_REGULATOR (22 chars). Widen to VARCHAR(50).
    conn.execute(
        text(
            "ALTER TABLE alerts "
            "ALTER COLUMN disposition TYPE VARCHAR(50) USING disposition::VARCHAR(50)"
        )
    )

    # Phase 4 — v2 case workflow
    conn.execute(
        text(
            "ALTER TABLE investigations ADD COLUMN IF NOT EXISTS "
            "review_status VARCHAR(30) NOT NULL DEFAULT 'AI_COMPLETE'"
        )
    )
    conn.execute(
        text(
            "UPDATE alerts SET status = 'PENDING_OFFICER_REVIEW' "
            "WHERE UPPER(status) = 'ESCALATED'"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_investigations_alert_id_unique "
            "ON investigations (alert_id)"
        )
    )


def create_tables_and_migrate() -> None:
    engine = get_engine()
    create_tables(engine)
    with engine.begin() as conn:
        run_migrations(conn)
