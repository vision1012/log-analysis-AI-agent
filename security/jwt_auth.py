"""JWT access tokens for authenticated API sessions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

_DEFAULT_DEV_SECRET = "dev-only-change-me-in-production"
_ALGORITHM = "HS256"


class JWTConfigurationError(RuntimeError):
    """Raised when JWT settings are missing or invalid."""


class JWTValidationError(Exception):
    """Raised when a token is invalid or expired."""


def _jwt_secret() -> str:
    secret = (os.environ.get("JWT_SECRET") or "").strip()
    if secret:
        return secret
    env = (os.environ.get("ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    if env in {"production", "prod", "staging"}:
        raise JWTConfigurationError("JWT_SECRET is required in production/staging")
    return _DEFAULT_DEV_SECRET


def _jwt_expires_minutes() -> int:
    raw = (os.environ.get("JWT_EXPIRES_MINUTES") or "1440").strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise JWTConfigurationError("JWT_EXPIRES_MINUTES must be an integer") from exc
    if minutes < 1:
        raise JWTConfigurationError("JWT_EXPIRES_MINUTES must be >= 1")
    return minutes


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str | None = None,
) -> str:
    """Return a signed JWT for the authenticated user."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=_jwt_expires_minutes()),
    }
    if role:
        payload["role"] = role
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate signature and expiry; return JWT claims."""
    if not token or not token.strip():
        raise JWTValidationError("missing token")
    try:
        return jwt.decode(
            token.strip(),
            _jwt_secret(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub", "email"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise JWTValidationError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTValidationError("invalid token") from exc
