"""
Password login API (no JWT or session middleware in this phase).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.services.users_service import InvalidCredentialsError, UserNotFoundError, login_svc
from schemas.auth import LoginRequest
from schemas.users import UserResponse

router = APIRouter()


@router.post("/auth/login", response_model=UserResponse)
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
