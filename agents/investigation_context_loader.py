"""Load read-only investigation context for multi-agent analysis."""

from __future__ import annotations

import os
from typing import Any

from agents.agent_models import AgentInvestigationContext
from feedback.feedback_learning_service import get_feedback_for_investigation
from graph.graph_visualization_service import investigation_exists
from graph.investigation_retriever import InvestigationGraphRetriever
from graph.neo4j_client import Neo4jClient
from graph.similar_incident_service import find_similar_investigations
from investigation.timeline_service import build_investigation_timeline

TRAVERSAL_MAX_HOPS = 10


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def _service_name_from_record(record: dict[str, Any]) -> str:
    merged = (record.get("derived_signals_snapshot") or {}).get("merged") or {}
    services = merged.get("service_names") or (record.get("future_graph_links") or {}).get("services") or []
    if isinstance(services, list) and services:
        return str(services[0])
    bundle = record.get("relationship_ready_bundle") or {}
    candidates = bundle.get("candidate_services") or []
    if isinstance(candidates, list) and candidates:
        return str(candidates[0])
    return ""


def _fetch_builds(client: Neo4jClient, investigation_id: str) -> list[dict[str, Any]]:
    rows = client.execute_read(
        f"""
        MATCH (i:Investigation {{id: $investigation_id}})
        OPTIONAL MATCH (i)-[*1..{TRAVERSAL_MAX_HOPS}]-(b:Build)
        WITH DISTINCT b
        WHERE b IS NOT NULL
        RETURN b.id AS build_id,
               b.build_number AS build_number,
               b.status AS status,
               b.branch AS branch,
               b.commit_sha AS commit_sha,
               b.started_at AS started_at,
               b.completed_at AS completed_at,
               b.build_url AS build_url
        ORDER BY b.started_at DESC
        """,
        {"investigation_id": investigation_id},
    )
    return [dict(row) for row in rows]


def load_agent_investigation_context(
    client: Neo4jClient,
    investigation_id: str,
) -> AgentInvestigationContext:
    """Assemble timeline, graph, store, and feedback context for agent analysis."""
    if not investigation_exists(client, investigation_id):
        raise KeyError(f"investigation not found: {investigation_id}")

    retriever = InvestigationGraphRetriever(client)
    store_record: dict[str, Any] = {}
    try:
        loaded = _get_investigation_store().get_record(investigation_id)
        if isinstance(loaded, dict):
            store_record = loaded
    except Exception:
        store_record = {}

    ticket_key = str(store_record.get("ticket_key") or "")
    service_name = _service_name_from_record(store_record)

    deployments = retriever.get_related_deployments(investigation_id=investigation_id)
    if not service_name and deployments:
        service_name = deployments[0].service_name

    alerts = retriever.get_related_alerts(investigation_id=investigation_id)
    incidents = retriever.get_related_incidents(investigation_id=investigation_id)
    runbooks = retriever.get_runbooks_for_service(service_name) if service_name else []
    known_issues: list = []
    for alert in alerts[:3]:
        known_issues.extend(retriever.get_known_issues_for_alert(alert.alert_id))

    similar = find_similar_investigations(client, investigation_id, limit=5)
    feedback = get_feedback_for_investigation(client, investigation_id)
    timeline = build_investigation_timeline(client, investigation_id)
    builds = _fetch_builds(client, investigation_id)

    return AgentInvestigationContext(
        investigation_id=investigation_id,
        ticket_key=ticket_key,
        service_name=service_name,
        timeline_events=timeline,
        deployments=deployments,
        builds=builds,
        alerts=alerts,
        incidents=incidents,
        runbooks=runbooks,
        known_issues=known_issues,
        similar_investigations=similar,
        feedback=feedback,
        store_record=store_record,
    )
