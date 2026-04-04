"""OpenAPI contract for user signup: no legacy ``name`` field on POST /api/v1/users."""

from __future__ import annotations

from api.main import app
from schemas.users import UserCreate


def _user_create_schema_from_openapi() -> dict:
    schema = app.openapi()
    ref = (
        schema.get("paths", {})
        .get("/api/v1/users", {})
        .get("post", {})
        .get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref", "")
    )
    assert ref, "missing POST /api/v1/users requestBody schema ref"
    name = ref.split("/")[-1]
    return schema["components"]["schemas"][name]


def test_openapi_user_create_has_no_name_field() -> None:
    m = _user_create_schema_from_openapi()
    props = set((m.get("properties") or {}).keys())
    assert "name" not in props, "UserCreate must not expose a name field (use first_name, last_name)"
    assert "first_name" in props
    assert "last_name" in props


def test_openapi_user_create_required_excludes_name() -> None:
    m = _user_create_schema_from_openapi()
    required = set(m.get("required") or [])
    assert "name" not in required
    assert "first_name" in required
    assert "last_name" in required


def test_post_users_json_without_name_returns_not_422_schema_error() -> None:
    """Valid payload without ``name`` must pass Pydantic (no Field missing for name)."""
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "email": "test-user-openapi@example.com",
        "password": "Valid1!Pass",
        "role": "developer",
        "team": "qa",
    }
    assert "name" not in payload
    u = UserCreate.model_validate(payload)
    assert u.first_name == "Test"
    assert u.last_name == "User"
