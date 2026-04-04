"""
User management API: create and read users from PostgreSQL.
Passwords are stored hashed; use ``POST /api/v1/auth/login`` for password login (no JWT in this phase).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.exc import OperationalError, ProgrammingError

from api.rate_limit.deps import rate_limit
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
logger = logging.getLogger(__name__)


def _is_undefined_column_error(exc: ProgrammingError) -> bool:
    """True when Postgres reports a missing column (migrations not applied)."""
    orig = getattr(exc, "orig", None)
    raw = str(orig or exc)
    lower = raw.lower()
    return "undefinedcolumn" in lower or "does not exist" in lower


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("users_post"))],
)
async def create_user_endpoint(body: UserCreate) -> UserResponse:
    """Create a user with a public role; rejects duplicate email.

    Request body is :class:`schemas.users.UserCreate` (``first_name``, ``last_name``, …) — not a single ``name`` field.
    """
    try:
        return create_user_svc(body)
    except DuplicateUserEmailError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_email",
                "message": "email already exists",
                "email": e.email,
            },
        ) from e
    except OperationalError as e:
        # e.g. host unreachable — avoid opaque 500 for a valid JSON body
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": "Could not reach the database. Check POSTGRES_URL and network.",
            },
        ) from e
    except ValueError as e:
        # get_postgres_url() raises if POSTGRES_URL is missing (common in misconfigured containers)
        if "POSTGRES_URL" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "database_unconfigured",
                    "message": str(e),
                },
            ) from e
        raise
    except ProgrammingError as e:
        # Typical cause: ORM expects columns (e.g. email_verification_*) not present until migration 002+.
        if _is_undefined_column_error(e):
            logger.warning("signup failed: database schema missing columns: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "database_schema_mismatch",
                    "message": (
                        "PostgreSQL users table is missing required columns. "
                        "Apply db/postgres/schema.sql to new databases, or run migrations in "
                        "db/postgres/migrations/ in order (at minimum 002 for email verification columns)."
                    ),
                },
            ) from e
        raise


@router.get("/users", response_model=UserListResponse)
async def list_users_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> UserListResponse:
    """List users (newest first) with pagination metadata."""
    return list_users_svc(limit=limit, offset=offset)


@router.get(
    "/users/by-email/{email}",
    response_model=UserResponse,
    dependencies=[Depends(rate_limit("users_by_email"))],
)
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
