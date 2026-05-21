"""Central settings from environment (with sensible defaults for local demo)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

from trade_surveillance.supabase_project import project_ref_from_database_url, supabase_api_url


@dataclass(frozen=True)
class Settings:
    # ── API ──────────────────────────────────────────────────────────────────
    app_env: str
    allowed_origins: str
    auto_migrate_on_startup: bool
    database_url: str

    # ── Auth ─────────────────────────────────────────────────────────────────
    # Optional fallback for GoTrue HTTP login if service role key is unavailable.
    supabase_anon_key: str
    # Supabase JWT secret — Project Settings → API → JWT Secret.
    # Leave empty to disable JWT validation (APP_ENV=development only).
    supabase_jwt_secret: str
    # Optional: https://<project-ref>.supabase.co/auth/v1
    # When set, JWT issuer claim is validated. Strongly recommended for production.
    supabase_jwt_issuer: str

    # ── Agent / LLM ──────────────────────────────────────────────────────────
    anthropic_api_key: str   # Required for POST /investigations/run/:id

    # ── Supabase Storage (ML pipeline artefacts) ─────────────────────────────
    supabase_url: str
    supabase_service_key: str
    storage_bucket: str
    features_key: str   # path inside bucket for features.parquet
    model_key: str      # path inside bucket for isolation_forest.pkl
    medians_key: str    # path inside bucket for medians.json


def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    database_url = _env_str("DATABASE_URL", "")

    supabase_url = _env_str("SUPABASE_URL", "")
    if not supabase_url:
        ref = project_ref_from_database_url(database_url)
        if ref:
            supabase_url = supabase_api_url(ref)

    jwt_issuer = _env_str("SUPABASE_JWT_ISSUER", "")
    if not jwt_issuer and supabase_url:
        jwt_issuer = f"{supabase_url.rstrip('/')}/auth/v1"

    return Settings(
        app_env=_env_str("APP_ENV", "development"),
        allowed_origins=_env_str("ALLOWED_ORIGINS", "http://localhost:3000"),
        auto_migrate_on_startup=_env_bool("AUTO_MIGRATE_ON_STARTUP", True),
        database_url=database_url,
        supabase_anon_key=_env_str("SUPABASE_ANON_KEY", ""),
        supabase_jwt_secret=_env_str("SUPABASE_JWT_SECRET", ""),
        supabase_jwt_issuer=jwt_issuer,
        anthropic_api_key=_env_str("ANTHROPIC_API_KEY", ""),
        supabase_url=supabase_url,
        supabase_service_key=_env_str("SUPABASE_SERVICE_ROLE_KEY", ""),
        storage_bucket=_env_str("SUPABASE_STORAGE_BUCKET", "trade-surveillance-artifacts"),
        features_key=_env_str("SUPABASE_FEATURES_KEY", "features/features.parquet"),
        model_key=_env_str("SUPABASE_MODEL_KEY", "model/isolation_forest.pkl"),
        medians_key=_env_str("SUPABASE_MEDIANS_KEY", "model/medians.json"),
    )


def clear_settings_cache() -> None:
    """Used in tests to pick up changed environment variables."""
    get_settings.cache_clear()
