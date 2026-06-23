"""API route tests for conference demo mode."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from demo.demo_models import DemoLaunchResult, DemoScenario
from schemas.users import UserResponse


def _user() -> UserResponse:
    return UserResponse(
        user_id="user-1",
        first_name="Demo",
        last_name="User",
        email="demo@example.com",
        created_at=datetime.now(timezone.utc),
    )


def test_list_demo_scenarios_endpoint() -> None:
    from api.routes.demo_routes import list_demo_scenarios_endpoint

    scenarios = [
        DemoScenario(
            scenario_id="auth-failure",
            title="Authentication Failure",
            description="demo",
            service_name="auth-service",
            severity="critical",
            ticket_key="OPS-101",
            root_cause="/srv/auth/handler.py",
            resolution="rollback",
            confidence=0.88,
        )
    ]
    with patch("api.routes.demo_routes.list_scenarios", return_value=scenarios):
        body = asyncio.run(list_demo_scenarios_endpoint())

    assert len(body["scenarios"]) == 1
    assert body["scenarios"][0]["scenario_id"] == "auth-failure"


def test_launch_demo_scenario_endpoint() -> None:
    from api.routes.demo_routes import launch_demo_scenario_endpoint

    launch = DemoLaunchResult(
        scenario_id="auth-failure",
        investigation_id="inv-1",
        ticket_key="OPS-101",
        service_name="auth-service",
        root_cause="/srv/auth/handler.py",
        confidence=0.88,
        resolution="rollback",
        graph_nodes=10,
        graph_relationships=15,
        timeline_event_count=8,
        feedback_seeded=True,
    )
    with patch("api.routes.demo_routes.launch_scenario", return_value=launch):
        body = asyncio.run(
            launch_demo_scenario_endpoint("auth-failure", current_user=_user())
        )

    assert body["launch"]["investigation_id"] == "inv-1"
    assert body["launch"]["feedback_seeded"] is True


def test_get_demo_scenario_not_found() -> None:
    from api.routes.demo_routes import get_demo_scenario_endpoint

    with patch("api.routes.demo_routes.load_scenario", side_effect=KeyError("missing")):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_demo_scenario_endpoint("missing"))

    assert exc.value.status_code == 404
