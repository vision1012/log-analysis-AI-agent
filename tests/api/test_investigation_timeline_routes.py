"""API route tests for investigation timeline workspace."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from investigation.timeline_models import InvestigationTimelineEvent


def test_investigation_timeline_endpoint_success() -> None:
    from api.routes.investigation_graph import get_investigation_timeline_endpoint

    events = [
        InvestigationTimelineEvent(
            event_id="evt-1",
            timestamp="2024-01-01T09:00:00Z",
            event_type="JIRA_CREATED",
            source="Jira",
            title="Auth outage",
        ),
        InvestigationTimelineEvent(
            event_id="evt-2",
            timestamp="2024-01-01T10:00:00Z",
            event_type="ALERT_TRIGGERED",
            source="Datadog",
            title="Error rate high",
            severity="high",
        ),
    ]
    with patch("api.routes.investigation_graph.fetch_investigation_timeline", return_value=events):
        body = asyncio.run(
            get_investigation_timeline_endpoint(
                "inv-1",
                from_ts=None,
                to_ts=None,
                event_type=None,
            )
        )

    assert body["investigation_id"] == "inv-1"
    assert len(body["events"]) == 2
    assert body["events"][0]["event_type"] == "JIRA_CREATED"


def test_investigation_timeline_endpoint_not_found() -> None:
    from api.routes.investigation_graph import get_investigation_timeline_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_investigation_timeline",
        side_effect=InvestigationGraphNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                get_investigation_timeline_endpoint(
                    "missing",
                    from_ts=None,
                    to_ts=None,
                    event_type=None,
                )
            )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "investigation_graph_not_found"


def test_investigation_timeline_endpoint_passes_filters() -> None:
    from api.routes.investigation_graph import get_investigation_timeline_endpoint

    with patch("api.routes.investigation_graph.fetch_investigation_timeline", return_value=[]) as mocked:
        asyncio.run(
            get_investigation_timeline_endpoint(
                "inv-1",
                from_ts="2024-01-01T00:00:00Z",
                to_ts="2024-01-02T00:00:00Z",
                event_type="ALERT_TRIGGERED",
            )
        )

    mocked.assert_called_once_with(
        "inv-1",
        from_ts="2024-01-01T00:00:00Z",
        to_ts="2024-01-02T00:00:00Z",
        event_type="ALERT_TRIGGERED",
    )
