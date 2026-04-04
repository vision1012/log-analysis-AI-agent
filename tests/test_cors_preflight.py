"""CORS: preflight and cross-origin GET /health (browser parity with TestClient)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
)
def test_options_users_preflight_succeeds(client: TestClient, origin: str) -> None:
    r = client.options(
        "/api/v1/users",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    assert "POST" in (r.headers.get("access-control-allow-methods") or "")


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
)
def test_get_health_includes_cors_for_dev_origins(client: TestClient, origin: str) -> None:
    """Simulates fetch('http://127.0.0.1:8000/health', { headers }) from a Vite tab."""
    r = client.get("/health", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
