"""Signup maps Postgres undefined-column errors to 503 with a clear code."""

from __future__ import annotations

from unittest.mock import patch

import psycopg2.errors
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from api.main import app


def test_create_user_programming_error_undefined_column_returns_503() -> None:
    orig = psycopg2.errors.UndefinedColumn(
        'column "email_verification_token_hash" of relation "users" does not exist\n'
    )
    exc = ProgrammingError("INSERT INTO users ...", {}, orig)

    with patch("api.routers.users_routes.create_user_svc", side_effect=exc):
        client = TestClient(app)
        r = client.post(
            "/api/v1/users",
            json={
                "first_name": "A",
                "last_name": "B",
                "email": "a@example.com",
                "password": "Valid1!Pass",
                "role": "developer",
            },
        )
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["code"] == "database_schema_mismatch"
