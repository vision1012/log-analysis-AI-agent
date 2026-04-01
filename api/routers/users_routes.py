"""
User management API: create and read users from PostgreSQL (no JWT auth in this phase).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, status

from api.services.users_service import (
    DuplicateUserEmailError,
    InvalidEmailError,
    UserNotFoundError,
    create_user_svc,
    get_user_by_email_svc,
    get_user_by_id_svc,
    list_users_svc,
)
from schemas.users import UserCreate, UserListResponse, UserResponse

router = APIRouter()


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_endpoint(body: UserCreate) -> UserResponse:
    """Create a user with a public role; rejects duplicate email."""
    try:
        return create_user_svc(body)
    except DuplicateUserEmailError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_email",
                "message": str(e),
                "email": e.email,
            },
        ) from e


@router.get("/users", response_model=UserListResponse)
async def list_users_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> UserListResponse:
    """List users (newest first) with pagination metadata."""
    return list_users_svc(limit=limit, offset=offset)


@router.get("/users/by-email/{email}", response_model=UserResponse)
async def get_user_by_email_endpoint(
    email: str = Path(..., min_length=3, max_length=320, description="Email address (URL-encoded if needed)"),
) -> UserResponse:
    """Resolve a user by email (case-insensitive)."""
    try:
        return get_user_by_email_svc(email)
    except InvalidEmailError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_email",
                "message": str(e),
                "email": e.raw,
            },
        ) from e
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "user_not_found",
                "message": str(e),
                "email": e.email,
            },
        ) from e


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_by_id_endpoint(
    user_id: str = Path(..., min_length=1, description="User UUID"),
) -> UserResponse:
    """Fetch a user by ``user_id``."""
    try:
        return get_user_by_id_svc(user_id)
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "user_not_found",
                "message": str(e),
                "user_id": e.user_id,
            },
        ) from e
