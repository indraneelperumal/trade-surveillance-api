from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from trade_surveillance.auth_supabase import (
    SupabaseAuthError,
    auth_api_key,
    refresh_session,
    sign_in_with_password,
)
from trade_surveillance.config import get_settings
from trade_surveillance.schemas.auth import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthTokenResponse,
    AuthUserInfo,
)
from trade_surveillance.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")
ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _to_response(session) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        token_type=session.token_type,
        user=AuthUserInfo(id=session.user_id, email=session.email),
    )


def _dev_login_response(email: str) -> AuthTokenResponse:
    """Local dev when GoTrue is not configured; paired with auth._dev_bypass_active()."""
    return AuthTokenResponse(
        access_token="",
        refresh_token="",
        expires_in=0,
        user=AuthUserInfo(id="__dev__", email=email),
    )


@router.post("/login", response_model=AuthTokenResponse, responses=ERROR_RESPONSES)
def login(payload: AuthLoginRequest) -> AuthTokenResponse:
    """
    Email/password sign-in via Supabase Auth (server-side).

    Returns JWT access + refresh tokens for the frontend to send as Bearer on API calls.
    """
    settings = get_settings()
    if not auth_api_key(settings):
        if settings.app_env == "development":
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set — returning dev login stub. "
                "Configure service role key for real auth."
            )
            return _dev_login_response(str(payload.email))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        )
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Supabase project URL could not be resolved. Set SUPABASE_URL or use a "
                "Supabase DATABASE_URL (postgres.<project-ref> user)."
            ),
        )
    try:
        session = sign_in_with_password(settings, str(payload.email), payload.password)
    except SupabaseAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _to_response(session)


@router.post("/refresh", response_model=AuthTokenResponse, responses=ERROR_RESPONSES)
def refresh_tokens(payload: AuthRefreshRequest) -> AuthTokenResponse:
    settings = get_settings()
    if not auth_api_key(settings) or not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        )
    try:
        session = refresh_session(settings, payload.refresh_token)
    except SupabaseAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _to_response(session)
