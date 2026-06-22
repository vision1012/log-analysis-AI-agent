"""User CRUD and password login backed by PostgreSQL ``users`` table."""

from __future__ import annotations

from typing import Optional
from urllib.parse import unquote

from db.postgres.connection import get_db_session, get_db_session_readonly
from db.postgres.repository import (
    DuplicateUserEmailError,
    count_users,
    get_user_by_email,
    get_user_by_id,
    list_users as list_users_repo,
)
from api.services.auth_lifecycle import create_user_with_verification
from schemas.auth import LoginRequest, LoginResponse
from schemas.users import UserCreate, UserListResponse, UserResponse
from security.jwt_auth import create_access_token
from security.passwords import verify_password


class UserNotFoundError(Exception):
    """No user for the given id or email."""

    def __init__(self, *, user_id: Optional[str] = None, email: Optional[str] = None) -> None:
        self.user_id = user_id
        self.email = email
        if user_id is not None:
            super().__init__(f"user not found: {user_id!r}")
        elif email is not None:
            super().__init__(f"user not found for email: {email!r}")
        else:
            super().__init__("user not found")


class InvalidEmailError(Exception):
    """Email path parameter is not a valid address."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__("invalid email format")


class InvalidCredentialsError(Exception):
    """Password did not match stored hash."""

    def __init__(self) -> None:
        super().__init__("invalid email or password")


class EmailNotVerifiedError(Exception):
    """Login rejected until email is verified."""

    def __init__(self, *, email: str) -> None:
        self.email = email
        super().__init__("email not verified")


def create_user_svc(body: UserCreate) -> UserResponse:
    """Insert user, send verification email; raises DuplicateUserEmailError on unique email violation."""
    return create_user_with_verification(body)


def login_svc(body: LoginRequest) -> LoginResponse:
    """Resolve user by email and verify password; returns user fields and JWT.

    **Verified-only login:** if ``is_email_verified`` is false, raises
    :class:`EmailNotVerifiedError` (mapped to HTTP 403 by the auth router). There is no
    bypass. Password is checked first so wrong credentials yield 401 without revealing
    verification state.
    """
    with get_db_session_readonly() as session:
        row = get_user_by_email(session, body.email)
        if row is None:
            raise UserNotFoundError(email=body.email)
        if not verify_password(body.password, row.password_hash):
            raise InvalidCredentialsError()
        if not row.is_email_verified:
            raise EmailNotVerifiedError(email=body.email)
        user = UserResponse.model_validate(row)
        token = create_access_token(
            user_id=user.user_id,
            email=user.email,
            role=user.role,
        )
        return LoginResponse(**user.model_dump(), access_token=token)


def list_users_svc(limit: int = 50, offset: int = 0) -> UserListResponse:
    with get_db_session_readonly() as session:
        total = count_users(session)
        rows = list_users_repo(session, limit=limit, offset=offset)
        users = [UserResponse.model_validate(r) for r in rows]
    return UserListResponse(users=users, total=total, limit=limit, offset=offset)


def get_user_by_id_svc(user_id: str) -> UserResponse:
    uid = user_id.strip()
    if not uid:
        raise UserNotFoundError(user_id=user_id)
    with get_db_session_readonly() as session:
        row = get_user_by_id(session, uid)
        if row is None:
            raise UserNotFoundError(user_id=uid)
        # Build response while session is open (avoid detached ORM / 500 on attribute access).
        return UserResponse.model_validate(row)


def get_user_by_email_svc(email: str) -> UserResponse:
    # Path segment may be URL-encoded (e.g. %40); Starlette usually decodes once — unquote is idempotent.
    raw = unquote(email).strip()
    normalized = raw.lower()
    if not normalized or "@" not in normalized:
        raise InvalidEmailError(email)
    with get_db_session_readonly() as session:
        row = get_user_by_email(session, normalized)
        if row is None:
            raise UserNotFoundError(email=normalized)
        return UserResponse.model_validate(row)
