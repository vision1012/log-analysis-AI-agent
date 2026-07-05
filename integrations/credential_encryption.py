"""App-level encryption for integration connection credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_DEV_KEY_MATERIAL = b"log-analysis-ai-agent-dev-integration-encryption-v1"
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(api[_-]?token|token|password|secret|authorization|bearer)\s*[:=]\s*\S+"
)


class IntegrationEncryptionError(RuntimeError):
    """Raised when encryption configuration or operations fail."""


class IntegrationEncryptionConfigurationError(IntegrationEncryptionError):
    """Raised when required encryption settings are missing in production."""


def is_production_mode() -> bool:
    env = (os.environ.get("ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    return env in {"production", "prod", "staging"}


def ensure_encryption_key_configured() -> None:
    """Fail fast in production when ``INTEGRATION_ENCRYPTION_KEY`` is unset."""
    if is_production_mode() and not (os.environ.get("INTEGRATION_ENCRYPTION_KEY") or "").strip():
        raise IntegrationEncryptionConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY is required in production/staging"
        )


def _normalize_fernet_key(raw: str) -> bytes:
    key = raw.strip().encode("utf-8")
    try:
        Fernet(key)
        return key
    except Exception:
        digest = hashlib.sha256(key).digest()
        return base64.urlsafe_b64encode(digest)


def _encryption_key_bytes() -> bytes:
    raw = (os.environ.get("INTEGRATION_ENCRYPTION_KEY") or "").strip()
    if raw:
        return _normalize_fernet_key(raw)
    if is_production_mode():
        raise IntegrationEncryptionConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY is required in production/staging"
        )
    logger.warning(
        "integration_encryption: INTEGRATION_ENCRYPTION_KEY not set; using dev-only derived key"
    )
    return base64.urlsafe_b64encode(hashlib.sha256(_DEV_KEY_MATERIAL).digest())


def _fernet() -> Fernet:
    return Fernet(_encryption_key_bytes())


def encrypt_credentials(payload: dict[str, Any]) -> str:
    """Serialize and encrypt a credential payload dict."""
    if not isinstance(payload, dict):
        raise IntegrationEncryptionError("credential payload must be a dict")
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _fernet().encrypt(plaintext).decode("ascii")


def decrypt_credentials(encrypted: str) -> dict[str, Any]:
    """Decrypt and deserialize a credential payload dict."""
    if not (encrypted or "").strip():
        raise IntegrationEncryptionError("encrypted credentials are empty")
    try:
        plaintext = _fernet().decrypt(encrypted.encode("ascii"))
    except InvalidToken as exc:
        raise IntegrationEncryptionError("failed to decrypt credentials") from exc
    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        raise IntegrationEncryptionError("decrypted credentials must be a JSON object")
    return data


def mask_sensitive_text(text: str) -> str:
    """Redact token-like substrings from error messages."""
    if not text:
        return text
    masked = _SENSITIVE_VALUE_RE.sub(r"\1=***", text)
    return masked.replace("Bearer ", "Bearer ***")
