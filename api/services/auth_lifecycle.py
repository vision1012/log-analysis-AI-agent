"""Email verification and password reset flows (no JWT)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from db.postgres.connection import get_db_session, get_db_session_readonly
from db.postgres.repository import (
    create_user,
    get_user_by_email,
    get_user_by_email_verification_token_hash,
    get_user_by_password_reset_token_hash,
)
from db.postgres.models import User
from api.email.sender import send_plain_text_email
from api.email.settings import load_email_settings
from schemas.users import UserCreate, UserResponse
from security.passwords import hash_password
from security.tokens import generate_url_safe_token, hash_token
from security.validation import normalize_and_validate_email, validate_signup_password

logger = logging.getLogger("api.auth_lifecycle")


class AuthTokenError(Exception):
    """Verification or reset token is missing, invalid, or expired."""

    pass


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _verification_link(raw_token: str) -> str:
    base = load_email_settings().app_base_url.rstrip("/")
    return f"{base}/api/v1/auth/verify-email?token={raw_token}"


def _reset_link(raw_token: str) -> str:
    base = load_email_settings().app_base_url.rstrip("/")
    return f"{base}/reset-password?token={raw_token}"


def send_verification_email(to_email: str, raw_token: str) -> None:
    settings = load_email_settings()
    link = _verification_link(raw_token)
    body = (
        f"Verify your email for Log Analysis AI Agent by opening this link:\n\n{link}\n\n"
        f"This link expires in {settings.email_verification_ttl_hours} hours.\n"
    )
    send_plain_text_email(to_email, "Verify your email", body)


def send_password_reset_email(to_email: str, raw_token: str) -> None:
    settings = load_email_settings()
    link = _reset_link(raw_token)
    body = (
        f"Reset your password using this link:\n\n{link}\n\n"
        f"This link expires in {settings.password_reset_ttl_hours} hours.\n"
        "If you did not request a reset, ignore this email.\n"
    )
    send_plain_text_email(to_email, "Password reset", body)


def attach_email_verification_to_new_user(user: User) -> str:
    """Set verification fields on an already-persisted user; return raw token for email."""
    settings = load_email_settings()
    raw = generate_url_safe_token()
    user.is_email_verified = False
    user.email_verification_token_hash = hash_token(raw)
    user.email_verification_expires_at = _utcnow_naive() + timedelta(
        hours=settings.email_verification_ttl_hours
    )
    return raw


def create_user_with_verification(body: UserCreate) -> UserResponse:
    """Create user, attach verification token, send email."""
    payload = {
        "name": body.name.strip(),
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": body.role,
        "team": body.team.strip() if body.team else None,
    }
    if body.user_id is not None:
        payload["user_id"] = body.user_id

    with get_db_session() as session:
        row = create_user(session, payload)
        raw_token = attach_email_verification_to_new_user(row)
        session.flush()
        try:
            send_verification_email(row.email, raw_token)
        except Exception as exc:
            logger.warning("verification email send failed email=%s err=%s", row.email, exc)
        return UserResponse.model_validate(row)


def verify_email_token(raw_token: str) -> UserResponse:
    if not raw_token or not raw_token.strip():
        raise AuthTokenError("missing token")
    th = hash_token(raw_token.strip())
    with get_db_session() as session:
        user = get_user_by_email_verification_token_hash(session, th)
        if user is None:
            raise AuthTokenError("invalid token")
        if user.email_verification_expires_at and user.email_verification_expires_at < _utcnow_naive():
            user.email_verification_token_hash = None
            user.email_verification_expires_at = None
            session.flush()
            raise AuthTokenError("expired token")
        user.is_email_verified = True
        user.email_verification_token_hash = None
        user.email_verification_expires_at = None
        session.flush()
        return UserResponse.model_validate(user)


def resend_verification_email(raw_email: str) -> None:
    """Send another verification email if user exists and is unverified."""
    email = normalize_and_validate_email(raw_email)
    with get_db_session() as session:
        user = get_user_by_email(session, email)
        if user is None or user.is_email_verified:
            return
        raw = generate_url_safe_token()
        user.email_verification_token_hash = hash_token(raw)
        user.email_verification_expires_at = _utcnow_naive() + timedelta(
            hours=load_email_settings().email_verification_ttl_hours
        )
        session.flush()
        try:
            send_verification_email(user.email, raw)
        except Exception as exc:
            logger.warning("resend verification email failed email=%s err=%s", user.email, exc)


def forgot_password_request(raw_email: str) -> None:
    """Generate reset token if user exists; send email. Caller returns generic message."""
    email = normalize_and_validate_email(raw_email)
    with get_db_session() as session:
        user = get_user_by_email(session, email)
        if user is None:
            return
        raw = generate_url_safe_token()
        user.password_reset_token_hash = hash_token(raw)
        user.password_reset_expires_at = _utcnow_naive() + timedelta(
            hours=load_email_settings().password_reset_ttl_hours
        )
        session.flush()
        try:
            send_password_reset_email(user.email, raw)
        except Exception as exc:
            logger.warning("password reset email failed email=%s err=%s", user.email, exc)


def reset_password_with_token(raw_token: str, new_password: str) -> UserResponse:
    validate_signup_password(new_password)
    if not raw_token or not raw_token.strip():
        raise AuthTokenError("missing token")
    th = hash_token(raw_token.strip())
    with get_db_session() as session:
        user = get_user_by_password_reset_token_hash(session, th)
        if user is None:
            raise AuthTokenError("invalid token")
        if user.password_reset_expires_at and user.password_reset_expires_at < _utcnow_naive():
            user.password_reset_token_hash = None
            user.password_reset_expires_at = None
            session.flush()
            raise AuthTokenError("expired token")
        user.password_hash = hash_password(new_password)
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        session.flush()
        return UserResponse.model_validate(user)
