"""Unit tests for rate-limit key resolution (no Redis)."""

from __future__ import annotations

from starlette.requests import Request

from api.rate_limit.keys import client_ip, resolve_rate_limit_key


def _request(method: str, path: str, headers: dict | None = None, state: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("test", 80),
    }
    r = Request(scope)
    if state:
        for k, v in state.items():
            setattr(r.state, k, v)
    return r


def test_resolve_jobs_post_uses_body_user() -> None:
    req = _request("POST", "/api/v1/jobs", state={"rate_limit_user_id": "abc-uuid"})
    assert "u:abc-uuid" in resolve_rate_limit_key(req, "jobs_post")


def test_resolve_jobs_post_falls_back_to_ip() -> None:
    req = _request("POST", "/api/v1/jobs")
    k = resolve_rate_limit_key(req, "jobs_post")
    assert k.startswith("ip:")


def test_resolve_rca_uses_header_user() -> None:
    req = _request("GET", "/api/v1/rca/results/x", headers={"X-User-Id": "user-1"})
    assert resolve_rate_limit_key(req, "rca_results") == "u:user-1"


def test_users_post_is_ip_only() -> None:
    req = _request("POST", "/api/v1/users", headers={"X-User-Id": "ignored"})
    k = resolve_rate_limit_key(req, "users_post")
    assert k.startswith("ip:")


def test_client_ip_x_forwarded() -> None:
    req = _request("GET", "/", headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"})
    assert client_ip(req) == "203.0.113.5"
