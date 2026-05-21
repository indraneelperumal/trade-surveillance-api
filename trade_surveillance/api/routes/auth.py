from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from trade_surveillance.auth import get_current_user
from trade_surveillance.auth_supabase import (
    SupabaseAuthError,
    auth_api_key,
    refresh_session,
    sign_in_with_password,
)
from trade_surveillance.config import get_settings
from trade_surveillance.crud import users as users_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.domain.enums import ROLE_ANALYST
from trade_surveillance.models.user import User
from trade_surveillance.schemas.auth import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthSessionResponse,
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


def _auth_user_from_db(user: User | None, *, fallback_id: str, fallback_email: str) -> AuthUserInfo:
    if user:
        return AuthUserInfo(
            id=str(user.id),
            email=user.email,
            role=user.role or ROLE_ANALYST,
            display_name=user.display_name,
        )
    return AuthUserInfo(id=fallback_id, email=fallback_email, role=ROLE_ANALYST)


def _to_response(session, db: Session) -> AuthTokenResponse:
    app_user = users_crud.get_user_by_supabase_uid(db, session.user_id)
    return AuthTokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        token_type=session.token_type,
        user=_auth_user_from_db(app_user, fallback_id=session.user_id, fallback_email=session.email),
    )


def _dev_login_response(email: str, db: Session) -> AuthTokenResponse:
    """Local dev when GoTrue is not configured; paired with auth._dev_bypass_active()."""
    app_user = users_crud.ensure_app_user(db, supabase_uid="__dev__", email=email)
    return AuthTokenResponse(
        access_token="",
        refresh_token="",
        expires_in=0,
        user=_auth_user_from_db(app_user, fallback_id="__dev__", fallback_email=email),
    )


@router.get("/session", response_model=AuthSessionResponse, responses=ERROR_RESPONSES)
def get_session(current_user: User = Depends(get_current_user)) -> AuthSessionResponse:
    return AuthSessionResponse(
        user=AuthUserInfo(
            id=str(current_user.id),
            email=current_user.email,
            role=current_user.role or ROLE_ANALYST,
            display_name=current_user.display_name,
        )
    )


@router.post("/login", response_model=AuthTokenResponse, responses=ERROR_RESPONSES)
def login(
    payload: AuthLoginRequest,
    db: Session = Depends(get_db_session),
) -> AuthTokenResponse:
    settings = get_settings()
    if not auth_api_key(settings):
        if settings.app_env == "development":
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set — returning dev login stub. "
                "Configure service role key for real auth."
            )
            return _dev_login_response(str(payload.email), db)
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

    users_crud.ensure_app_user(
        db,
        supabase_uid=session.user_id,
        email=session.email,
    )
    return _to_response(session, db)


@router.post("/refresh", response_model=AuthTokenResponse, responses=ERROR_RESPONSES)
def refresh_tokens(
    payload: AuthRefreshRequest,
    db: Session = Depends(get_db_session),
) -> AuthTokenResponse:
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
    users_crud.ensure_app_user(
        db,
        supabase_uid=session.user_id,
        email=session.email,
    )
    return _to_response(session, db)
