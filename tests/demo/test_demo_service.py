"""Tests for conference demo mode service."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from demo.demo_service import launch_scenario, list_scenarios, load_scenario


def test_list_scenarios_returns_five() -> None:
    scenarios = list_scenarios()
    assert len(scenarios) == 5
    ids = {scenario.scenario_id for scenario in scenarios}
    assert ids == {
        "auth-failure",
        "k8s-oomkilled",
        "db-connection-exhaustion",
        "payment-deploy-failure",
        "api-latency-regression",
    }


def test_load_scenario_returns_rich_metadata() -> None:
    scenario = load_scenario("auth-failure")
    assert scenario.title == "Authentication Failure"
    assert scenario.service_name == "auth-service"
    assert scenario.ticket_key == "OPS-101"
    assert scenario.timeline_events
    assert scenario.graph_entities
    assert scenario.similar_incidents
    assert scenario.confidence > 0


def test_load_scenario_unknown_raises() -> None:
    with pytest.raises(KeyError, match="unknown demo scenario"):
        load_scenario("does-not-exist")


@patch("demo.demo_service.build_investigation_timeline", return_value=[MagicMock(), MagicMock()])
@patch("demo.demo_service._seed_feedback", return_value=True)
@patch("demo.demo_service._persist_graph", return_value={"nodes": 12, "relationships": 18})
@patch("demo.demo_service._get_investigation_store")
def test_launch_scenario_creates_investigation(
    mock_get_store,
    mock_persist_graph,
    mock_seed_feedback,
    mock_build_timeline,
    tmp_path,
) -> None:
    from artifacts.investigation_store import LocalFileInvestigationStore

    store = LocalFileInvestigationStore(tmp_path)
    mock_get_store.return_value = store
    client = MagicMock()
    client._driver = object()

    result = launch_scenario("auth-failure", user_id="user-1", graph_client=client)

    assert result.scenario_id == "auth-failure"
    assert result.investigation_id
    assert result.ticket_key == "OPS-101"
    assert result.graph_nodes == 12
    assert result.graph_relationships == 18
    assert result.timeline_event_count == 2
    assert result.feedback_seeded is True
    assert result.rca_completed is True

    record = store.get_record(result.investigation_id)
    assert record is not None
    assert record["run_status"] == "completed"
    assert record["relationship_ready_bundle"]["rca_target_file"] == "/srv/auth/handler.py"
    assert record["demo_scenario_id"] == "auth-failure"

    mock_persist_graph.assert_called_once()
    mock_seed_feedback.assert_called_once()
    mock_build_timeline.assert_called_once()


def test_each_scenario_includes_required_entities() -> None:
    required_timeline_types = {
        "JIRA_CREATED",
        "BUILD_COMPLETED",
        "DEPLOYMENT_COMPLETED",
        "ALERT_TRIGGERED",
        "INCIDENT_OPENED",
        "RUNBOOK_MATCHED",
        "RCA_COMPLETED",
    }
    for scenario in list_scenarios():
        event_types = {event["event_type"] for event in scenario.timeline_events}
        assert required_timeline_types.issubset(event_types), scenario.scenario_id
        entities = scenario.graph_entities
        assert entities.get("jira_tickets", 0) >= 1
        assert entities.get("alerts", 0) >= 1
        assert entities.get("pagerduty_incidents", 0) >= 1
        assert entities.get("runbooks", 0) >= 1
        assert scenario.root_cause
        assert scenario.confidence > 0
