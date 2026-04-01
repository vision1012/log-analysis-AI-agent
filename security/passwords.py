"""Bcrypt password hashing and verification (no raw passwords stored)."""

from __future__ import annotations

import bcrypt

# Minimum length for signup and password change (aligned with API validation).
MIN_PASSWORD_LENGTH: int = 8


def hash_password(plain: str) -> str:
    """Return a bcrypt hash string suitable for ``users.password_hash``."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    """Return True if ``plain`` matches ``password_hash``."""
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False
