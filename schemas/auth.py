"""Schemas for password-based auth and JWT session responses."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field, field_validator

from schemas.users import UserResponse
from security.validation import normalize_and_validate_email, validate_signup_password


class LoginRequest(BaseModel):
    """Body for ``POST /api/v1/auth/login``."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return normalize_and_validate_email(v)


class VerifyEmailBody(BaseModel):
    """Body for ``POST /api/v1/auth/verify-email``."""

    token: str = Field(..., min_length=1, max_length=512)


class ResendVerificationBody(BaseModel):
    """Body for resend verification (``/auth/resend-verification`` or ``/auth/verify-email/resend``)."""

    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return normalize_and_validate_email(v)


class ForgotPasswordBody(BaseModel):
    """Body for ``POST /api/v1/auth/forgot-password``."""

    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return normalize_and_validate_email(v)


class ResetPasswordBody(BaseModel):
    """Body for ``POST /api/v1/auth/reset-password``."""

    token: str = Field(..., min_length=1, max_length=512)
    new_password: str = Field(
        ...,
        max_length=256,
        description="New password (same strength rules as signup)",
        validation_alias=AliasChoices("new_password", "password"),
    )

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        validate_signup_password(v)
        return v


class GenericAuthMessageResponse(BaseModel):
    """Non-leaky response for forgot-password / resend flows."""

    message: str


class LoginResponse(UserResponse):
    """Successful login: user profile fields plus JWT access token."""

    access_token: str
    token_type: str = "bearer"
