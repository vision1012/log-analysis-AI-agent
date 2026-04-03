"""Opaque token generation and storage as SHA-256 hex digests (no raw tokens in DB)."""

from __future__ import annotations

import hashlib
import secrets


def generate_url_safe_token(num_bytes: int = 32) -> str:
    """Return a high-entropy URL-safe string for email links."""
    return secrets.token_urlsafe(num_bytes)


def hash_token(raw: str) -> str:
    """Hash a raw token for persistence and lookup (constant-length hex)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_token(raw: str, stored_hash: str | None) -> bool:
    """Timing-safe compare of raw token to stored hash."""
    if not raw or not stored_hash:
        return False
    return secrets.compare_digest(hash_token(raw), stored_hash)
