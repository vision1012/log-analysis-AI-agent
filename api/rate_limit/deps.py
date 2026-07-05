"""FastAPI rate limits via Redis fixed-window backend."""

import logging

from fastapi import HTTPException, Request, status

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
        "rca_results",
        "rca_explanation",
        "auth_verify_email",
        "auth_resend_verification",
        "auth_forgot_password",
        "auth_reset_password",
    }
)


def _raise_rate_limit_exceeded(scope: str, request: Request) -> None:
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


class _ScopedRateLimit:
    """
    FastAPI dependency that enforces per-scope Redis limits without inspecting ``route.path``.

    ``fastapi_limiter.depends.RateLimiter`` breaks on routes registered via
    ``include_router`` (``_IncludedRouter`` has no ``path``). Keys use scope + client
    identifier only — sufficient because each scope maps to one policy/limit.
    """

    __slots__ = ("scope", "limiter")

    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.limiter = RedisFixedWindowLimiter(scope=scope, window_seconds=_WINDOW_SECONDS)

    async def __call__(self, request: Request) -> None:
        ident = resolve_rate_limit_key(request, self.scope)
        ok = await self.limiter.try_acquire_async(name=ident, blocking=False)
        if not ok:
            _raise_rate_limit_exceeded(self.scope, request)


def rate_limit(scope: str) -> _ScopedRateLimit:
    """
    Build a rate-limit dependency backed by Redis (see ``RedisFixedWindowLimiter``).

    Keys: user id from headers or ``request.state.rate_limit_user_id`` (job create body),
    else client IP — see ``resolve_rate_limit_key``.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"unknown rate limit scope: {scope}")
    return _ScopedRateLimit(scope)
