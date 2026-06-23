"""API layer for multi-agent investigation mode."""

from __future__ import annotations

from agents.agent_models import MultiAgentInvestigationReport
from agents.investigation_coordinator import run_multi_agent_investigation
from api.services.investigation_graph_service import InvestigationGraphNotFoundError
from graph.neo4j_client import Neo4jClient


def fetch_multi_agent_investigation_report(investigation_id: str) -> MultiAgentInvestigationReport:
    client = Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        return run_multi_agent_investigation(client, investigation_id)
    except KeyError as exc:
        raise InvestigationGraphNotFoundError(str(exc)) from exc
    finally:
        if getattr(client, "_driver", None):
            client.close()
