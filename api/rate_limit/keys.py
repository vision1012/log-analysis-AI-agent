"""Derive rate-limit keys: prefer user id when available, else client IP."""

from __future__ import annotations

import hashlib
import re

from starlette.requests import Request

# Optional headers clients may send when no JWT exists yet (mirrors job body user id).
USER_ID_HEADERS: tuple[str, ...] = ("X-User-Id", "X-Triggered-By-User-Id")


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _safe_segment(s: str, max_len: int = 160) -> str:
    """Avoid odd Redis keys; keep readable enough for debugging."""
    t = re.sub(r"[^\w.\-:@+]", "_", s.strip())[:max_len]
    return t or "anon"


def resolve_rate_limit_key(request: Request, scope: str) -> str:
    """
    Return a stable string for Redis keying.

    - ``jobs_post``: ``request.state.rate_limit_user_id`` (from JSON body middleware), else headers, else IP.
    - ``rca_results``, ``rca_explanation``: headers, else IP.
    - Other scopes: IP only.
    """
    if scope == "jobs_post":
        uid = getattr(request.state, "rate_limit_user_id", None)
        if isinstance(uid, str) and uid.strip():
            return f"u:{_safe_segment(uid)}"
        for h in USER_ID_HEADERS:
            raw = request.headers.get(h)
            if raw and raw.strip():
                return f"u:{_safe_segment(raw)}"
        return f"ip:{_safe_segment(client_ip(request))}"

    if scope in ("rca_results", "rca_explanation"):
        for h in USER_ID_HEADERS:
            raw = request.headers.get(h)
            if raw and raw.strip():
                return f"u:{_safe_segment(raw)}"
        return f"ip:{_safe_segment(client_ip(request))}"

    return f"ip:{_safe_segment(client_ip(request))}"


def redis_key_hash(scope: str, logical_key: str) -> str:
    """Short hash so Redis keys stay bounded even if inputs grow."""
    h = hashlib.sha256(f"{scope}:{logical_key}".encode()).hexdigest()[:32]
    return f"{scope}:{h}"
