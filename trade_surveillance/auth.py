"""
JWT-based auth dependency for FastAPI.

Supabase Auth issues access tokens as HS256 (legacy JWT secret) or ES256 (JWKS).
`get_current_user` validates the Bearer token and returns the app-level User record.

Dev bypass (APP_ENV=development only): when auth is not fully configured,
unauthenticated requests are allowed as a synthetic COMPLIANCE_LEAD user.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from trade_surveillance.auth_supabase import auth_api_key
from trade_surveillance.config import get_settings
from trade_surveillance.crud import users as users_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.jwt_verify import decode_supabase_jwt, jwt_validation_available
from trade_surveillance.models.user import User

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _dev_bypass_active(settings) -> bool:
    """Match POST /auth/login dev stub — no GoTrue and/or no JWT validation."""
    if settings.app_env != "development":
        return False
    if not jwt_validation_available(settings):
        return True
    if not auth_api_key(settings):
        return True
    return False


def _make_dev_user() -> User:
    """In-memory user for local dev when GoTrue / JWT is not fully configured."""
    now = datetime.now(timezone.utc)
    return User(
        id=uuid4(),
        email="dev@localhost",
        display_name="Dev (no auth)",
        role="COMPLIANCE_LEAD",
        is_active=True,
        supabase_uid="__dev__",
        created_at=now,
        updated_at=now,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db_session),
) -> User:
    """
    Validates a Supabase Bearer JWT and returns the matching app User.

    HTTP 401 — token missing, expired, or invalid.
    HTTP 403 — user not provisioned in the users table or account inactive.
    HTTP 503 — auth not configured in a non-development environment.
    """
    settings = get_settings()

    if _dev_bypass_active(settings):
        if not jwt_validation_available(settings):
            logger.warning(
                "JWT validation not configured in development — "
                "JWT validation DISABLED. Set SUPABASE_URL or SUPABASE_JWT_SECRET."
            )
        elif not auth_api_key(settings):
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set in development — "
                "API accepts unauthenticated requests as dev user."
            )
        if credentials is None:
            return _make_dev_user()

    if not jwt_validation_available(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is not configured on this server. "
                "Set SUPABASE_URL (ES256) or SUPABASE_JWT_SECRET (HS256)."
            ),
        )

    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Include 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_supabase_jwt(credentials.credentials.strip(), settings)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please sign in again.",
        )
    except jwt.InvalidTokenError:
        logger.debug("JWT validation failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    supabase_uid: str | None = payload.get("sub")
    if not supabase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing the 'sub' claim.",
        )

    email = str(payload.get("email") or "").strip()
    user = users_crud.get_user_by_supabase_uid(db, str(supabase_uid))
    if user is None or not user.is_active:
        if not email:
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Authenticated but no app account found. "
                        "Sign out and sign in again, or ask an admin to provision your account."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is inactive. Contact an admin.",
            )
        user = users_crud.ensure_app_user(
            db,
            supabase_uid=str(supabase_uid),
            email=email,
        )

    return user


def require_compliance_lead(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "COMPLIANCE_LEAD":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the COMPLIANCE_LEAD role.",
        )
    return current_user
