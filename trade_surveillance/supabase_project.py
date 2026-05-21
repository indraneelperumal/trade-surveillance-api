"""Derive Supabase project URL / issuer from a Supabase Postgres DATABASE_URL."""

from __future__ import annotations

from urllib.parse import unquote, urlparse


def project_ref_from_database_url(database_url: str) -> str | None:
    """
    Extract project ref from common Supabase connection strings.

    Supports pooler URLs (user ``postgres.<ref>``) and direct host ``db.<ref>.supabase.co``.
    """
    if not database_url:
        return None

    normalized = database_url
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql://"):
        if normalized.startswith(prefix):
            normalized = "postgresql://" + normalized[len(prefix) :]
            break

    parsed = urlparse(normalized)
    username = unquote(parsed.username or "")
    if username.startswith("postgres."):
        ref = username.split(".", 1)[1]
        return ref or None

    host = (parsed.hostname or "").lower()
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host[3 : -len(".supabase.co")] or None

    return None


def supabase_api_url(project_ref: str) -> str:
    return f"https://{project_ref}.supabase.co"


def supabase_jwt_issuer(project_ref: str) -> str:
    return f"{supabase_api_url(project_ref)}/auth/v1"
