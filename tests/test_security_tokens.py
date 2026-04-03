"""Unit tests for token hashing (no DB)."""

from __future__ import annotations

from security.tokens import hash_token, verify_token


def test_hash_token_stable() -> None:
    h = hash_token("hello-token")
    assert len(h) == 64
    assert hash_token("hello-token") == h


def test_verify_token() -> None:
    raw = "abc"
    h = hash_token(raw)
    assert verify_token(raw, h) is True
    assert verify_token("wrong", h) is False
