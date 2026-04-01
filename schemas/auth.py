"""Schemas for password-based auth (no JWT in this phase)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """Body for ``POST /api/v1/auth/login``."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        s = v.strip().lower()
        if "@" not in s:
            raise ValueError("invalid email format")
        return s
