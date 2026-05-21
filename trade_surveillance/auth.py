"""
JWT-based auth dependency for FastAPI.

Supabase Auth issues HS256 JWTs signed with the project JWT secret.
`get_current_user` validates the token and returns the app-level User record.

Dev bypass (APP_ENV=development only): when Supabase auth is not fully configured
(no JWT secret, or no service role / anon key for GoTrue login), unauthenticated
requests are allowed as a synthetic COMPLIANCE_LEAD user. Production always
requires a valid Bearer JWT when SUPABASE_JWT_SECRET is set.
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
from trade_surveillance.models.user import User

logger = logging.getLogger(__name__)

# auto_error=False lets us provide a custom 401 and implement the dev bypass.
_bearer = HTTPBearer(auto_error=False)


def _dev_bypass_active(settings) -> bool:
    """Match POST /auth/login dev stub — no GoTrue and/or no JWT validation."""
    if settings.app_env != "development":
        return False
    if not settings.supabase_jwt_secret:
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
    HTTP 503 — JWT secret missing in a non-development environment (mis-config).
    """
    settings = get_settings()
    jwt_secret = settings.supabase_jwt_secret

    if _dev_bypass_active(settings):
        if not jwt_secret:
            logger.warning(
                "SUPABASE_JWT_SECRET not set in development — "
                "JWT validation DISABLED. Never deploy without it."
            )
        elif not auth_api_key(settings):
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set in development — "
                "API accepts unauthenticated requests as dev user."
            )
        if credentials is None:
            return _make_dev_user()

    if not jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is not configured on this server. "
                "Set SUPABASE_JWT_SECRET in the environment variables."
            ),
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Include 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=settings.supabase_jwt_issuer or None,
            options={
                # Only validate issuer if we have one configured.
                "verify_iss": bool(settings.supabase_jwt_issuer),
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please sign in again.",
        )
    except jwt.InvalidTokenError:
        # Avoid leaking internal JWT parse errors to callers.
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

    user = users_crud.get_user_by_supabase_uid(db, supabase_uid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Authenticated but no app account found. "
                "Ask an admin to provision your account in the users table."
            ),
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive. Contact an admin.",
        )

    return user


def require_compliance_lead(current_user: User = Depends(get_current_user)) -> User:
    """
    Role guard — only COMPLIANCE_LEAD accounts may call endpoints that use this.
    Stack on top of get_current_user: Depends(require_compliance_lead).
    """
    if current_user.role != "COMPLIANCE_LEAD":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the COMPLIANCE_LEAD role.",
        )
    return current_user
