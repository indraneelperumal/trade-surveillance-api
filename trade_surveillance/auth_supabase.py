"""Server-side Supabase Auth (GoTrue) — uses service role key, not the browser anon key."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from trade_surveillance.config import Settings

logger = logging.getLogger(__name__)


class SupabaseAuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SupabaseSession:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    user_id: str
    email: str


def auth_api_key(settings: Settings) -> str:
    """
    GoTrue HTTP API key (not DATABASE_URL).

    Login hits Supabase Auth (`/auth/v1/token`), a separate service from Postgres.
    Server-side we use the service role key you already have for Storage; anon is optional.
    """
    return settings.supabase_service_key or settings.supabase_anon_key


def _auth_headers(settings: Settings) -> dict[str, str]:
    key = auth_api_key(settings)
    if not key:
        raise SupabaseAuthError(
            "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) is not configured.",
            status_code=503,
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _parse_session(data: dict[str, Any]) -> SupabaseSession:
    user = data.get("user") or {}
    user_id = user.get("id")
    email = user.get("email")
    if not user_id or not email:
        raise SupabaseAuthError("Auth provider returned an incomplete user profile.", status_code=502)
    return SupabaseSession(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=int(data.get("expires_in", 3600)),
        token_type=data.get("token_type", "bearer"),
        user_id=str(user_id),
        email=str(email),
    )


def _raise_for_supabase_error(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    message = "Invalid email or password."
    try:
        body = resp.json()
        if isinstance(body, dict):
            message = body.get("error_description") or body.get("msg") or body.get("error") or message
    except Exception:
        logger.debug("Non-JSON Supabase auth error body", exc_info=True)
    status = 401 if resp.status_code in {400, 401, 422} else 502
    raise SupabaseAuthError(str(message), status_code=status)


def sign_in_with_password(settings: Settings, email: str, password: str) -> SupabaseSession:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/token?grant_type=password"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            url,
            headers=_auth_headers(settings),
            json={"email": email, "password": password},
        )
    _raise_for_supabase_error(resp)
    return _parse_session(resp.json())


def refresh_session(settings: Settings, refresh_token: str) -> SupabaseSession:
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/token?grant_type=refresh_token"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            url,
            headers=_auth_headers(settings),
            json={"refresh_token": refresh_token},
        )
    _raise_for_supabase_error(resp)
    return _parse_session(resp.json())
