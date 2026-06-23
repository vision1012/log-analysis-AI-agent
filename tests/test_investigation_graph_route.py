"""API route tests for investigation graph visualization."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from api.routes.investigation_graph import get_investigation_graph_endpoint
from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from fastapi import HTTPException


def test_investigation_graph_endpoint_success() -> None:
    graph = {
        "nodes": [
            {"id": "inv-1", "type": "Investigation", "label": "inv-1", "properties": {"id": "inv-1"}},
            {"id": "OPS-1", "type": "JiraTicket", "label": "Auth errors", "properties": {"issue_key": "OPS-1"}},
        ],
        "edges": [
            {
                "id": "inv-1->OPS-1:RELATED_TO",
                "source": "inv-1",
                "target": "OPS-1",
                "type": "RELATED_TO",
                "relationship": "HAS_JIRA_TICKET",
            }
        ],
    }
    with patch("api.routes.investigation_graph.fetch_investigation_graph", return_value=graph):
        body = asyncio.run(get_investigation_graph_endpoint("inv-1", depth=2))

    assert len(body["nodes"]) == 2
    assert body["edges"][0]["type"] == "RELATED_TO"


def test_investigation_graph_endpoint_not_found() -> None:
    with patch(
        "api.routes.investigation_graph.fetch_investigation_graph",
        side_effect=InvestigationGraphNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_investigation_graph_endpoint("missing", depth=2))

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "investigation_graph_not_found"


def test_similar_investigations_endpoint_success() -> None:
    from graph.retrieval_models import SimilarInvestigation

    items = [
        SimilarInvestigation(
            investigation_id="inv-old",
            similarity_score=0.72,
            matched_factors=["service_match", "alert_match"],
            root_cause="/srv/auth/handler.py",
            confidence=0.72,
            resolution_summary="Auth errors — status: completed",
            created_at="2024-01-01T10:00:00Z",
        )
    ]
    with patch("api.routes.investigation_graph.fetch_similar_investigations", return_value=items):
        from api.routes.investigation_graph import get_similar_investigations_endpoint

        body = asyncio.run(get_similar_investigations_endpoint("inv-1", limit=10))

    assert len(body["similar_investigations"]) == 1
    assert body["similar_investigations"][0]["similarity_score"] == 0.72
    assert "service_match" in body["similar_investigations"][0]["matched_factors"]
