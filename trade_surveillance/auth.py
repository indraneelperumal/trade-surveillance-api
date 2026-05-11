"""
JWT-based auth dependency for FastAPI.

Supabase Auth issues HS256 JWTs signed with the project JWT secret.
`get_current_user` validates the token and returns the app-level User record.

Dev bypass: if SUPABASE_JWT_SECRET is empty AND APP_ENV=development, validation
is skipped and a synthetic COMPLIANCE_LEAD user is returned. In all other
environments (staging, production) a missing secret is a hard error — the
server will refuse to start rather than silently grant full access.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from trade_surveillance.config import get_settings
from trade_surveillance.crud import users as users_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.models.user import User

logger = logging.getLogger(__name__)

# auto_error=False lets us provide a custom 401 and implement the dev bypass.
_bearer = HTTPBearer(auto_error=False)

# Synthetic user returned only in APP_ENV=development with no JWT secret.
_DEV_USER = User(
    id=uuid4(),
    email="dev@localhost",
    display_name="Dev (no auth)",
    role="COMPLIANCE_LEAD",
    is_active=True,
    supabase_uid="__dev__",
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

    if not jwt_secret:
        if settings.app_env == "development":
            logger.warning(
                "SUPABASE_JWT_SECRET not set in development — "
                "JWT validation DISABLED. Never deploy without it."
            )
            return _DEV_USER
        # Any other environment (staging, production): fail closed.
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
