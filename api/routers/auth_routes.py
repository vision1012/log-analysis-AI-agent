"""
Password login and email verification / password reset (no JWT or session middleware).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.rate_limit.deps import rate_limit
from api.services.auth_lifecycle import (
    AuthTokenError,
    forgot_password_request,
    resend_verification_email,
    reset_password_with_token,
    verify_email_token,
)
from api.services.users_service import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    UserNotFoundError,
    login_svc,
)
from schemas.auth import (
    ForgotPasswordBody,
    GenericAuthMessageResponse,
    LoginRequest,
    ResendVerificationBody,
    ResetPasswordBody,
    VerifyEmailBody,
)
from schemas.users import UserResponse

router = APIRouter()

_GENERIC_OK = GenericAuthMessageResponse(
    message="If an account exists for this address, further instructions were sent.",
)


@router.post(
    "/auth/login",
    response_model=UserResponse,
    dependencies=[Depends(rate_limit("auth_login"))],
)
async def login_endpoint(body: LoginRequest) -> UserResponse:
    """Authenticate by email and password; returns the same safe user shape as other user endpoints."""
    try:
        return login_svc(body)
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "user_not_found",
                "message": "no user found for this email",
                "email": e.email,
            },
        ) from e
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": str(e),
            },
        ) from e
    except EmailNotVerifiedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_not_verified",
                "message": "verify your email before signing in",
                "email": e.email,
            },
        ) from e


@router.get(
    "/auth/verify-email",
    response_model=UserResponse,
    dependencies=[Depends(rate_limit("auth_verify_email"))],
)
async def verify_email_get(token: str = Query(..., min_length=1, max_length=512)) -> UserResponse:
    """Confirm email using token from the verification link (query string)."""
    try:
        return verify_email_token(token)
    except AuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_or_expired_token", "message": str(e)},
        ) from e


@router.post(
    "/auth/verify-email",
    response_model=UserResponse,
    dependencies=[Depends(rate_limit("auth_verify_email"))],
)
async def verify_email_post(body: VerifyEmailBody) -> UserResponse:
    """Confirm email using token in JSON body."""
    try:
        return verify_email_token(body.token)
    except AuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_or_expired_token", "message": str(e)},
        ) from e


async def _resend_verification_handler(body: ResendVerificationBody) -> GenericAuthMessageResponse:
    """Resend verification email (same generic response whether or not the user exists)."""
    await asyncio.to_thread(resend_verification_email, body.email)
    return _GENERIC_OK


@router.post(
    "/auth/verify-email/resend",
    response_model=GenericAuthMessageResponse,
    dependencies=[Depends(rate_limit("auth_resend_verification"))],
)
async def resend_verification_endpoint(body: ResendVerificationBody) -> GenericAuthMessageResponse:
    return await _resend_verification_handler(body)


@router.post(
    "/auth/resend-verification",
    response_model=GenericAuthMessageResponse,
    dependencies=[Depends(rate_limit("auth_resend_verification"))],
)
async def resend_verification_endpoint_alias(body: ResendVerificationBody) -> GenericAuthMessageResponse:
    """Alias for ``/auth/verify-email/resend``."""
    return await _resend_verification_handler(body)


@router.post(
    "/auth/forgot-password",
    response_model=GenericAuthMessageResponse,
    dependencies=[Depends(rate_limit("auth_forgot_password"))],
)
async def forgot_password_endpoint(body: ForgotPasswordBody) -> GenericAuthMessageResponse:
    """Request a password reset email (generic response; does not reveal if email exists)."""
    await asyncio.to_thread(forgot_password_request, body.email)
    return _GENERIC_OK


@router.post(
    "/auth/reset-password",
    response_model=UserResponse,
    dependencies=[Depends(rate_limit("auth_reset_password"))],
)
async def reset_password_endpoint(body: ResetPasswordBody) -> UserResponse:
    """Set a new password using the reset token from email."""
    try:
        return reset_password_with_token(body.token, body.new_password)
    except AuthTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_or_expired_token", "message": str(e)},
        ) from e
