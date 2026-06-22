"""API route tests for multi-agent investigation mode."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from agents.agent_models import AgentFinding, MultiAgentInvestigationReport
from api.services.investigation_graph_service import InvestigationGraphNotFoundError


def _report() -> MultiAgentInvestigationReport:
    finding = AgentFinding(agent_name="timeline", summary="timeline analyzed", confidence=0.8)
    return MultiAgentInvestigationReport(
        investigation_id="inv-1",
        timeline_findings=finding,
        deployment_findings=AgentFinding(agent_name="deployment", summary="d"),
        infrastructure_findings=AgentFinding(agent_name="infrastructure", summary="i"),
        incident_findings=AgentFinding(agent_name="incident", summary="a"),
        knowledge_findings=AgentFinding(agent_name="knowledge", summary="k"),
        rca_findings=AgentFinding(agent_name="rca", summary="r", confidence=0.9),
        final_summary="Lead signal from rca agent (confidence 0.90): r",
    )


def test_multi_agent_investigation_endpoint_success() -> None:
    from api.routes.investigation_graph import run_multi_agent_investigation_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_multi_agent_investigation_report",
        return_value=_report(),
    ):
        body = asyncio.run(run_multi_agent_investigation_endpoint("inv-1"))

    assert body["report"]["investigation_id"] == "inv-1"
    assert body["report"]["timeline_findings"]["agent_name"] == "timeline"
    assert body["report"]["final_summary"]


def test_multi_agent_investigation_endpoint_not_found() -> None:
    from api.routes.investigation_graph import run_multi_agent_investigation_endpoint

    with patch(
        "api.routes.investigation_graph.fetch_multi_agent_investigation_report",
        side_effect=InvestigationGraphNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(run_multi_agent_investigation_endpoint("missing"))

    assert exc.value.status_code == 404
