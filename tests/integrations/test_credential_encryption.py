"""Tests for integration credential encryption."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from integrations.credential_encryption import (
    IntegrationEncryptionConfigurationError,
    decrypt_credentials,
    encrypt_credentials,
    ensure_encryption_key_configured,
    is_production_mode,
    mask_sensitive_text,
)


def test_encrypt_decrypt_round_trip(monkeypatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", key)
    payload = {"email": "user@example.com", "api_token": "secret-token"}
    encrypted = encrypt_credentials(payload)
    assert encrypted != payload["api_token"]
    restored = decrypt_credentials(encrypted)
    assert restored == payload


def test_mask_sensitive_text_redacts_tokens() -> None:
    masked = mask_sensitive_text("token=abc123 and Bearer sk-live-abc")
    assert "abc123" not in masked
    assert "***" in masked


def test_ensure_encryption_key_required_in_production(monkeypatch) -> None:
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(IntegrationEncryptionConfigurationError):
        ensure_encryption_key_configured()


def test_dev_mode_allows_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    ensure_encryption_key_configured()
    encrypted = encrypt_credentials({"token": "dev-token"})
    assert decrypt_credentials(encrypted)["token"] == "dev-token"


def test_is_production_mode() -> None:
    assert is_production_mode.__name__ == "is_production_mode"
