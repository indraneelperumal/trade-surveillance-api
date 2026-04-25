"""Central settings from environment (with sensible defaults for local demo)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_env: str
    api_port: int
    allowed_origins: str
    auto_migrate_on_startup: bool
    database_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    s3_bucket: str
    raw_prefix: str
    features_key: str
    anomalies_key: str
    model_key: str
    medians_key: str
    memos_prefix: str


def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return int(val)


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        app_env=_env_str("APP_ENV", "development"),
        api_port=_env_int("API_PORT", 8000),
        allowed_origins=_env_str("ALLOWED_ORIGINS", "http://localhost:3000"),
        auto_migrate_on_startup=_env_bool("AUTO_MIGRATE_ON_STARTUP", True),
        database_url=_env_str("DATABASE_URL", ""),
        supabase_url=_env_str("SUPABASE_URL", ""),
        supabase_anon_key=_env_str("SUPABASE_ANON_KEY", ""),
        supabase_service_role_key=_env_str("SUPABASE_SERVICE_ROLE_KEY", ""),
        s3_bucket=_env_str("TSP_S3_BUCKET", "trade-surveillance-bucket"),
        raw_prefix=_env_str("TSP_RAW_PREFIX", "raw/"),
        features_key=_env_str("TSP_FEATURES_KEY", "features/features.parquet"),
        anomalies_key=_env_str("TSP_ANOMALIES_KEY", "processed/anomalies.parquet"),
        model_key=_env_str("TSP_MODEL_KEY", "model/isolation_forest.pkl"),
        medians_key=_env_str("TSP_MEDIANS_KEY", "model/medians.json"),
        memos_prefix=_env_str("TSP_MEMOS_PREFIX", "memos"),
    )


def clear_settings_cache() -> None:
    """Used in tests to pick up changed environment variables."""
    get_settings.cache_clear()


def require_aws_profile() -> str:
    """Raise if AWS_PROFILE is missing (batch jobs and agents use named profiles)."""
    load_dotenv()
    profile = os.environ.get("AWS_PROFILE")
    if not profile:
        raise ValueError(
            "AWS_PROFILE is not set. Add it to .env or export it in your shell."
        )
    return profile
