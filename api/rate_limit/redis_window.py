"""Fixed-window counters in Redis (async)."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger("api.rate_limit")

_redis = None  # type: ignore[assignment]


def set_redis_client(client) -> None:
    global _redis
    _redis = client


def get_redis_client():
    return _redis


async def try_acquire(
    redis_key: str,
    limit: int,
    window_seconds: int,
    *,
    fail_open: bool,
) -> Tuple[bool, int]:
    """
    Increment counter for the current time window.

    Returns (allowed, retry_after_seconds). If Redis is unavailable and fail_open is True, returns (True, 0).
    """
    if limit <= 0:
        return True, 0

    r = _redis
    if r is None:
        if fail_open:
            logger.warning("rate_limit redis client missing; fail_open allowing request key=%s", redis_key)
            return True, 0
        return False, window_seconds

    window = int(time.time() // window_seconds)
    bucket = f"rl:{redis_key}:{window}"

    try:
        n = int(await r.incr(bucket))
        if n == 1:
            await r.expire(bucket, window_seconds + 1)
        if n <= limit:
            return True, 0
        # Over limit; estimate retry when window rolls
        now = time.time()
        elapsed = now % window_seconds
        retry_after = max(1, int(window_seconds - elapsed))
        return False, retry_after
    except Exception as exc:
        logger.warning("rate_limit redis error key=%s err=%s", redis_key, exc)
        if fail_open:
            return True, 0
        return False, window_seconds
