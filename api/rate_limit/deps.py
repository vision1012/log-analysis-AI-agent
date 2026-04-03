"""FastAPI rate limits via ``fastapi_limiter`` + Redis fixed-window backend."""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import HTTPException, Request, status
from fastapi_limiter.depends import RateLimiter

from api.rate_limit.keys import resolve_rate_limit_key
from api.rate_limit.redis_pyrate_adapter import RedisFixedWindowLimiter

logger = logging.getLogger("api.rate_limit")

_WINDOW_SECONDS = 60

_VALID_SCOPES = frozenset(
    {
        "users_post",
        "auth_login",
        "users_by_email",
        "jobs_post",
        "debug_agent_run",
        "rca_results",
        "rca_explanation",
        "auth_verify_email",
        "auth_resend_verification",
        "auth_forgot_password",
        "auth_reset_password",
    }
)


def _identifier_for_scope(scope: str) -> Callable:
    async def _ident(request: Request) -> str:
        return resolve_rate_limit_key(request, scope)

    return _ident


def _callback_for_scope(scope: str) -> Callable:
    async def _cb(request: Request, _response) -> None:
        logger.info(
            "rate_limit exceeded scope=%s path=%s",
            scope,
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit_exceeded",
                "message": "Too many requests for this endpoint. Try again later.",
                "scope": scope,
            },
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )

    return _cb


def rate_limit(scope: str) -> RateLimiter:
    """
    Build a ``RateLimiter`` dependency backed by Redis (see ``RedisFixedWindowLimiter``).

    Keys: user id from headers or ``request.state.rate_limit_user_id`` (job create body),
    else client IP — see ``resolve_rate_limit_key``.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"unknown rate limit scope: {scope}")

    return RateLimiter(
        limiter=RedisFixedWindowLimiter(scope=scope, window_seconds=_WINDOW_SECONDS),
        identifier=_identifier_for_scope(scope),
        callback=_callback_for_scope(scope),
        blocking=False,
    )
