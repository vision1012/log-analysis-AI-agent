"""Load rate-limit settings from environment (defaults match product policy)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _parse_requests_per_minute(raw: str, default: int) -> int:
    """Accept ``N`` or ``N/minute`` (case-insensitive)."""
    s = raw.strip()
    if not s:
        return default
    m = re.match(r"^(\d+)\s*/\s*minute\s*$", s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    try:
        return int(s)
    except ValueError:
        return default


def _env_requests_per_min(*keys: str, default: int) -> int:
    """First non-empty env wins; supports legacy ``*_PER_MIN`` integer-only names."""
    for k in keys:
        raw = os.environ.get(k, "").strip()
        if raw:
            return _parse_requests_per_minute(raw, default)
    return default


@dataclass(frozen=True)
class RateLimitSettings:
    enabled: bool
    redis_url: str
    fail_open: bool
    # Per-scope: requests per window (window is 60s unless overridden per scope below)
    users_post_per_min: int
    auth_login_per_min: int
    users_by_email_per_min: int
    jobs_post_per_min: int
    debug_agent_run_per_min: int
    rca_results_per_min: int
    rca_explanation_per_min: int
    auth_verify_email_per_min: int
    auth_resend_verification_per_min: int
    auth_forgot_password_per_min: int
    auth_reset_password_per_min: int


def load_rate_limit_settings() -> RateLimitSettings:
    return RateLimitSettings(
        enabled=_env_bool("RATE_LIMIT_ENABLED", True),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip(),
        fail_open=_env_bool("RATE_LIMIT_FAIL_OPEN", True),
        users_post_per_min=_env_requests_per_min(
            "RATE_LIMIT_USERS_CREATE",
            "RATE_LIMIT_USERS_POST_PER_MIN",
            default=5,
        ),
        auth_login_per_min=_env_requests_per_min(
            "RATE_LIMIT_AUTH_LOGIN",
            "RATE_LIMIT_AUTH_LOGIN_PER_MIN",
            default=10,
        ),
        users_by_email_per_min=_env_requests_per_min(
            "RATE_LIMIT_USERS_BY_EMAIL",
            "RATE_LIMIT_USERS_BY_EMAIL_PER_MIN",
            default=10,
        ),
        jobs_post_per_min=_env_requests_per_min(
            "RATE_LIMIT_JOBS_CREATE",
            "RATE_LIMIT_JOBS_POST_PER_MIN",
            default=20,
        ),
        debug_agent_run_per_min=_env_requests_per_min(
            "RATE_LIMIT_DEBUG_RUN",
            "RATE_LIMIT_DEBUG_AGENT_RUN_PER_MIN",
            default=5,
        ),
        rca_results_per_min=_env_requests_per_min(
            "RATE_LIMIT_RCA_RESULTS",
            "RATE_LIMIT_RCA_RESULTS_PER_MIN",
            default=60,
        ),
        rca_explanation_per_min=_env_requests_per_min(
            "RATE_LIMIT_RCA_EXPLANATION",
            "RATE_LIMIT_RCA_EXPLANATION_PER_MIN",
            default=30,
        ),
        auth_verify_email_per_min=_env_requests_per_min(
            "RATE_LIMIT_AUTH_VERIFY_EMAIL",
            default=10,
        ),
        auth_resend_verification_per_min=_env_requests_per_min(
            "RATE_LIMIT_AUTH_RESEND_VERIFICATION",
            default=10,
        ),
        auth_forgot_password_per_min=_env_requests_per_min(
            "RATE_LIMIT_AUTH_FORGOT_PASSWORD",
            default=10,
        ),
        auth_reset_password_per_min=_env_requests_per_min(
            "RATE_LIMIT_AUTH_RESET_PASSWORD",
            default=10,
        ),
    )
