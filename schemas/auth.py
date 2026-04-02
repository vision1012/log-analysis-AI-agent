"""Schemas for password-based auth (no JWT in this phase)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from security.validation import normalize_and_validate_email


class LoginRequest(BaseModel):
    """Body for ``POST /api/v1/auth/login``."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return normalize_and_validate_email(v)
