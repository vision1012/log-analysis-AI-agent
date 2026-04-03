"""Email delivery settings from environment (no secrets in code)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("api.email.settings")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_email_provider() -> str:
    """Return ``log`` or ``smtp``. Default ``log`` for local development."""
    raw = os.environ.get("EMAIL_PROVIDER", "log").strip().lower()
    if raw in ("smtp", "mail", "send"):
        return "smtp"
    if raw in ("log", "logging", "dev", "console", ""):
        return "log"
    logger.warning("unknown EMAIL_PROVIDER=%r; defaulting to log", os.environ.get("EMAIL_PROVIDER"))
    return "log"


@dataclass(frozen=True)
class EmailSettings:
    """SMTP + app URL for verification/reset links."""

    email_provider: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_use_tls: bool
    app_base_url: str
    email_verification_ttl_hours: int
    password_reset_ttl_hours: int


def load_email_settings() -> EmailSettings:
    return EmailSettings(
        email_provider=_parse_email_provider(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_username=os.environ.get("SMTP_USERNAME", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
        smtp_from_email=os.environ.get("SMTP_FROM_EMAIL", "").strip(),
        smtp_use_tls=os.environ.get("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes"),
        app_base_url=os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
        email_verification_ttl_hours=_env_int("EMAIL_VERIFICATION_TTL_HOURS", 24),
        password_reset_ttl_hours=_env_int("PASSWORD_RESET_TTL_HOURS", 1),
    )


def email_delivery_mode() -> str:
    """Return ``log`` or ``smtp`` (alias for :attr:`EmailSettings.email_provider`)."""
    return load_email_settings().email_provider
