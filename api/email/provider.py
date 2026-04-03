"""Pluggable email delivery: development logging vs SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from api.email.settings import EmailSettings

logger = logging.getLogger("api.email")


class EmailProvider(Protocol):
    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None: ...


class LogEmailProvider:
    """
    Development mode: no network. Logs the full message so verification/reset URLs are visible.
    """

    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None:
        sep = "=" * 72
        logger.info(
            "%s\n[EMAIL DEV] provider=log (no SMTP)\nTo: %s\nSubject: %s\n%s\n%s\n%s",
            sep,
            to_addr,
            subject,
            sep,
            body.rstrip(),
            sep,
        )


class SmtpEmailProvider:
    """Production-oriented SMTP delivery."""

    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None:
        s = self._settings
        if not s.smtp_host:
            raise RuntimeError(
                "EMAIL_PROVIDER=smtp requires SMTP_HOST. Set EMAIL_PROVIDER=log for local dev."
            )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.smtp_from_email or s.smtp_username or "noreply@localhost"
        msg["To"] = to_addr
        msg.set_content(body)

        if s.smtp_use_tls and s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                if s.smtp_use_tls:
                    smtp.starttls()
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)


def build_provider(settings: EmailSettings) -> EmailProvider:
    """Return the configured provider (``log`` or ``smtp``)."""
    if settings.email_provider == "smtp":
        return SmtpEmailProvider(settings)
    return LogEmailProvider()
