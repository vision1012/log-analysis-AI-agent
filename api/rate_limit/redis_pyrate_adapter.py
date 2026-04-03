"""
Redis fixed-window limiter compatible with ``fastapi_limiter.depends.RateLimiter``.

The stock ``pyrate_limiter.Limiter`` + in-memory/Redis bucket is not used here: a single
shared bucket would not isolate per-client keys correctly for our policy. Instead we
implement ``try_acquire_async`` and back it with :func:`api.rate_limit.redis_window.try_acquire`.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import HTTPException, status
from starlette.requests import Request

from api.rate_limit.config import RateLimitSettings, load_rate_limit_settings
from api.rate_limit.keys import redis_key_hash
from api.rate_limit.redis_window import get_redis_client, try_acquire

logger = logging.getLogger("api.rate_limit")

_SCOPE_LIMITS: dict[str, Callable[[RateLimitSettings], int]] = {
    "users_post": lambda s: s.users_post_per_min,
    "auth_login": lambda s: s.auth_login_per_min,
    "users_by_email": lambda s: s.users_by_email_per_min,
    "jobs_post": lambda s: s.jobs_post_per_min,
    "debug_agent_run": lambda s: s.debug_agent_run_per_min,
    "rca_results": lambda s: s.rca_results_per_min,
    "rca_explanation": lambda s: s.rca_explanation_per_min,
    "auth_verify_email": lambda s: s.auth_verify_email_per_min,
    "auth_resend_verification": lambda s: s.auth_resend_verification_per_min,
    "auth_forgot_password": lambda s: s.auth_forgot_password_per_min,
    "auth_reset_password": lambda s: s.auth_reset_password_per_min,
}


class RedisFixedWindowLimiter:
    """
    Minimal duck-typed limiter for ``fastapi_limiter.depends.RateLimiter``.

    ``name`` is the composite key built by ``RateLimiter`` (identifier + route indices).
    """

    def __init__(self, scope: str, window_seconds: int) -> None:
        self.scope = scope
        self.window_seconds = window_seconds

    def close(self) -> None:
        """Match ``pyrate_limiter.Limiter`` lifecycle (no-op)."""
        return None

    async def try_acquire_async(
        self,
        name: str = "pyrate",
        weight: int = 1,
        blocking: bool = True,
        timeout: float = -1,
    ) -> bool:
        _ = weight, blocking, timeout
        settings = load_rate_limit_settings()
        if not settings.enabled:
            return True

        if get_redis_client() is None and not settings.fail_open:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "rate_limit_unavailable",
                    "message": "Rate limiting is unavailable",
                },
            )

        limit = _SCOPE_LIMITS[self.scope](settings)
        rkey = redis_key_hash(self.scope, name)
        ok, _ = await try_acquire(
            rkey,
            limit,
            self.window_seconds,
            fail_open=settings.fail_open,
        )
        return ok
