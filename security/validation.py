"""Reusable validation for signup email and password strength (login uses email + presence only)."""

from __future__ import annotations

import re
import string
from typing import List

from email_validator import EmailNotValidError, validate_email


def normalize_and_validate_email(raw: str) -> str:
    """
    Trim whitespace, validate format, return normalized lowercase email for storage/lookup.

    Raises ValueError with message ``invalid email format`` on malformed input.
    """
    s = raw.strip()
    if not s:
        raise ValueError("invalid email format")
    try:
        validated = validate_email(s, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("invalid email format") from None
    # Normalized RFC form; lowercase for consistent lookups (matches existing API behavior).
    return validated.normalized.lower()


def _missing_password_character_types(password: str) -> List[str]:
    missing: List[str] = []
    if not re.search(r"[A-Z]", password):
        missing.append("uppercase letter")
    if not re.search(r"[a-z]", password):
        missing.append("lowercase letter")
    if not re.search(r"\d", password):
        missing.append("number")
    if not any(ch in string.punctuation for ch in password):
        missing.append("special character")
    return missing


def validate_signup_password(password: str) -> None:
    """
    Enforce signup password policy. Raises ValueError with a clear message for 422 responses.

    Policy: min 8 characters; at least one uppercase, lowercase, digit, and ASCII punctuation
    special character.
    """
    if len(password) < 8:
        raise ValueError("password too weak: must be at least 8 characters")
    missing = _missing_password_character_types(password)
    if missing:
        need = ", ".join(missing)
        raise ValueError(
            f"password missing required character types: must include {need}"
        )
