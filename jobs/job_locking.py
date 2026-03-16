"""
Per-anomaly lock utilities for RCA jobs.

Prevents duplicate concurrent RCA runs for the same anomaly.
Redis backend when available; in-memory fallback for single-process.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

LOCK_PREFIX = "rca_lock:"
DEFAULT_LOCK_TTL_SEC = 600  # 10 min auto-expiry to prevent deadlocks

# In-memory fallback
_memory_locks: dict[str, threading.Lock] = {}
_memory_guard = threading.Lock()


def _lock_key(anomaly_id: str) -> str:
    return f"{LOCK_PREFIX}{anomaly_id}"


def _get_redis():
    """Get Redis client if available. Returns None if not configured or redis not installed."""
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL")
    if not redis_url:
        return None
    try:
        import redis
        return redis.from_url(redis_url, decode_responses=True)
    except ImportError:
        return None


def _redis_acquire(anomaly_id: str, ttl_sec: float = DEFAULT_LOCK_TTL_SEC) -> bool:
    """Acquire lock via Redis SET NX EX. Returns True if acquired."""
    r = _get_redis()
    if not r:
        return False
    try:
        key = _lock_key(anomaly_id)
        return bool(r.set(key, "1", nx=True, ex=int(ttl_sec)))
    except Exception:
        return False


def _redis_release(anomaly_id: str) -> None:
    """Release Redis lock. Safe to call if not held; never raises."""
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(_lock_key(anomaly_id))
    except Exception:
        pass


def _redis_is_locked(anomaly_id: str) -> bool:
    r = _get_redis()
    if not r:
        return False
    try:
        return bool(r.exists(_lock_key(anomaly_id)))
    except Exception:
        return False


def _memory_acquire(anomaly_id: str, timeout_sec: Optional[float] = None) -> bool:
    with _memory_guard:
        if anomaly_id not in _memory_locks:
            _memory_locks[anomaly_id] = threading.Lock()
        lock = _memory_locks[anomaly_id]
    if timeout_sec is None or timeout_sec == 0:
        return lock.acquire(blocking=False)
    return lock.acquire(blocking=True, timeout=timeout_sec)


def _memory_release(anomaly_id: str) -> None:
    with _memory_guard:
        lock = _memory_locks.get(anomaly_id)
    if lock and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


def _memory_is_locked(anomaly_id: str) -> bool:
    with _memory_guard:
        lock = _memory_locks.get(anomaly_id)
    return lock.locked() if lock else False


def _use_redis() -> bool:
    return _get_redis() is not None


def acquire_lock(
    anomaly_id: str,
    timeout_sec: Optional[float] = None,
    *,
    lock_ttl_sec: float = DEFAULT_LOCK_TTL_SEC,
) -> bool:
    """
    Acquire per-anomaly lock. Returns True if acquired.

    timeout_sec: None or 0 = non-blocking. >0 = block up to that many seconds.
    lock_ttl_sec: Redis lock TTL (auto-expiry). Ignored for in-memory.
    """
    if _use_redis():
        if timeout_sec is None or timeout_sec == 0:
            return _redis_acquire(anomaly_id, ttl_sec=lock_ttl_sec)
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if _redis_acquire(anomaly_id, ttl_sec=lock_ttl_sec):
                return True
            time.sleep(0.2)
        return False
    return _memory_acquire(anomaly_id, timeout_sec)


def release_lock(anomaly_id: str) -> None:
    """
    Release per-anomaly lock. Safe to call in finally; idempotent; never raises.
    """
    if _use_redis():
        _redis_release(anomaly_id)
    else:
        _memory_release(anomaly_id)


def is_locked(anomaly_id: str) -> bool:
    """Check if anomaly is currently locked."""
    if _use_redis():
        return _redis_is_locked(anomaly_id)
    return _memory_is_locked(anomaly_id)


class LockContext:
    """
    Context manager for per-anomaly lock. Guarantees release in __exit__.
    Usage:
        with LockContext(anomaly_id, timeout_sec=0) as acquired:
            if acquired:
                ...
    """

    def __init__(
        self,
        anomaly_id: str,
        timeout_sec: Optional[float] = None,
        *,
        lock_ttl_sec: float = DEFAULT_LOCK_TTL_SEC,
    ):
        self.anomaly_id = anomaly_id
        self.timeout_sec = timeout_sec
        self.lock_ttl_sec = lock_ttl_sec
        self._acquired = False

    def __enter__(self) -> bool:
        self._acquired = acquire_lock(
            self.anomaly_id,
            timeout_sec=self.timeout_sec,
            lock_ttl_sec=self.lock_ttl_sec,
        )
        return self._acquired

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired:
            release_lock(self.anomaly_id)
