"""Verify Supabase Auth JWTs (legacy HS256 or asymmetric ES256 via JWKS)."""

from __future__ import annotations

import logging
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from trade_surveillance.config import Settings

logger = logging.getLogger(__name__)

_ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def jwt_validation_available(settings: Settings) -> bool:
    """True when the API can validate Bearer tokens from Supabase Auth."""
    return bool(settings.supabase_url or settings.supabase_jwt_secret)


def decode_supabase_jwt(token: str, settings: Settings) -> dict:
    """
    Decode and validate a Supabase access token.

    - New projects: ES256 / RS256 via JWKS (requires SUPABASE_URL).
    - Legacy: HS256 via SUPABASE_JWT_SECRET.
    """
    issuer = settings.supabase_jwt_issuer or None
    decode_kwargs: dict = {
        "audience": "authenticated",
        "issuer": issuer,
        "options": {
            "verify_aud": True,
            "verify_iss": bool(issuer),
        },
    }

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise exc

    alg = header.get("alg") or "HS256"

    if alg in _ASYMMETRIC_ALGORITHMS:
        if not settings.supabase_url:
            raise jwt.InvalidTokenError(
                "Asymmetric JWT requires SUPABASE_URL for JWKS verification."
            )
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[alg],
            **decode_kwargs,
        )

    if not settings.supabase_jwt_secret:
        raise jwt.InvalidTokenError(
            "HS256 JWT requires SUPABASE_JWT_SECRET (or use Supabase asymmetric signing keys)."
        )
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        **decode_kwargs,
    )
