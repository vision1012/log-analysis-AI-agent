"""Email delivery (log dev provider or SMTP)."""

from api.email.provider import EmailProvider, LogEmailProvider, SmtpEmailProvider, build_provider
from api.email.sender import send_plain_text_email

__all__ = [
    "EmailProvider",
    "LogEmailProvider",
    "SmtpEmailProvider",
    "build_provider",
    "send_plain_text_email",
]
