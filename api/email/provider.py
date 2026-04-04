"""Pluggable email delivery: log (dev), Resend API, or SMTP."""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from api.email.settings import EmailSettings

logger = logging.getLogger("api.email")

RESEND_API_URL = "https://api.resend.com/emails"


def _safe_api_error_snippet(raw: str, max_len: int = 400) -> str:
    """Truncate provider error JSON/text for logs (no secrets; bounded size)."""
    s = " ".join(raw.split())
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s or "(empty body)"


class EmailProvider(Protocol):
    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None: ...


class LogEmailProvider:
    """
    Development mode: no network. Logs the full message so verification/reset URLs are visible.
    Look for lines prefixed with VERIFICATION LINK / PASSWORD RESET LINK from auth_lifecycle, then the dump below.
    """

    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None:
        sep = "=" * 72
        logger.info(
            "%s\n[EMAIL_PROVIDER=log] No SMTP — message below is the full email.\n"
            "To: %s\nSubject: %s\n%s\n%s\n%s",
            sep,
            to_addr,
            subject,
            sep,
            body.rstrip(),
            sep,
        )


def _safe_smtp_exception_detail(exc: smtplib.SMTPException, max_len: int = 200) -> str:
    """Bounded server response for logs (no credentials)."""
    code = getattr(exc, "smtp_code", None)
    raw = getattr(exc, "smtp_error", b"") or b""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace").strip()
    else:
        text = str(raw).strip()
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return f"smtp_code={code} smtp_error={text or '(none)'}"


class SmtpEmailProvider:
    """SMTP delivery (e.g. Gmail: ``smtp.gmail.com:587`` + STARTTLS — not implicit SSL on 465)."""

    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None:
        s = self._settings
        if not s.smtp_host:
            raise RuntimeError(
                "EMAIL_PROVIDER=smtp requires SMTP_HOST. Set EMAIL_PROVIDER=log for local dev."
            )
        if not s.smtp_username or not s.smtp_password:
            raise RuntimeError(
                "EMAIL_PROVIDER=smtp requires SMTP_USERNAME and SMTP_PASSWORD. "
                "For Gmail, use an App Password (Google Account → Security → 2-Step Verification → App passwords)."
            )

        from_addr = s.smtp_from_email or s.smtp_username
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(body)

        try:
            # Port 465: implicit TLS (SMTP_SSL). Port 587: plain then STARTTLS (typical Gmail).
            if s.smtp_use_tls and s.smtp_port == 465:
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                    smtp.login(s.smtp_username, s.smtp_password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                    if s.smtp_use_tls:
                        smtp.starttls()
                    smtp.login(s.smtp_username, s.smtp_password)
                    smtp.send_message(msg)
        except OSError as exc:
            logger.warning(
                "smtp send failed host=%s port=%s to=%s subject=%s err_type=%s",
                s.smtp_host,
                s.smtp_port,
                to_addr,
                subject,
                type(exc).__name__,
            )
            raise RuntimeError("smtp email send failed") from exc
        except smtplib.SMTPException as exc:
            logger.warning(
                "smtp send failed host=%s port=%s to=%s subject=%s err_type=%s %s",
                s.smtp_host,
                s.smtp_port,
                to_addr,
                subject,
                type(exc).__name__,
                _safe_smtp_exception_detail(exc),
            )
            raise RuntimeError("smtp email send failed") from exc


class ResendEmailProvider:
    """Send via Resend HTTP API (Bearer ``RESEND_API_KEY``)."""

    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    def send_plain_text(self, to_addr: str, subject: str, body: str) -> None:
        s = self._settings
        if not s.resend_api_key:
            raise RuntimeError(
                "EMAIL_PROVIDER=resend requires RESEND_API_KEY. Set EMAIL_PROVIDER=log for local dev."
            )
        if not s.email_from:
            raise RuntimeError(
                "EMAIL_PROVIDER=resend requires EMAIL_FROM (verified sender in Resend)."
            )

        payload = {
            "from": s.email_from,
            "to": [to_addr],
            "subject": subject,
            "text": body,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            RESEND_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {s.resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "log-analysis-AI-agent/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            msg_id = ""
            try:
                parsed = json.loads(raw) if raw.strip() else {}
                if isinstance(parsed, dict) and parsed.get("id"):
                    msg_id = str(parsed["id"])[:120]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            if msg_id:
                logger.info("resend api accepted id=%s to=%s", msg_id, to_addr)
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                pass
            safe = _safe_api_error_snippet(err_body)
            logger.warning(
                "resend send failed status=%s to=%s subject=%s err_type=%s detail=%s",
                exc.code,
                to_addr,
                subject,
                type(exc).__name__,
                safe,
            )
            raise RuntimeError("resend email send failed") from exc
        except OSError as exc:
            logger.warning(
                "resend send failed to=%s subject=%s err_type=%s",
                to_addr,
                subject,
                type(exc).__name__,
            )
            raise RuntimeError("resend email send failed") from exc


def build_provider(settings: EmailSettings) -> EmailProvider:
    """Return the configured provider (``log``, ``resend``, or ``smtp``)."""
    if settings.email_provider == "smtp":
        return SmtpEmailProvider(settings)
    if settings.email_provider == "resend":
        return ResendEmailProvider(settings)
    return LogEmailProvider()
