"""Build MCP graph context dict for deterministic RCA signal computation."""

from __future__ import annotations

from typing import Any

from graph.investigation_retriever import InvestigationGraphRetriever
from graph.neo4j_client import Neo4jClient


def _compact(record: Any, *, text_limit: int = 200) -> dict[str, Any]:
    data = record.model_dump() if hasattr(record, "model_dump") else dict(record)
    for key, value in list(data.items()):
        if isinstance(value, str) and len(value) > text_limit:
            data[key] = value[: text_limit - 3] + "..."
    return data


def build_mcp_graph_context(
    client: Neo4jClient,
    *,
    investigation_id: str = "",
    service_name: str = "",
    ticket_key: str = "",
    alert_id: str = "",
    max_items: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch investigation-graph records for MCP RCA signals."""
    empty: dict[str, list[dict[str, Any]]] = {
        "related_commits": [],
        "related_deployments": [],
        "related_alerts": [],
        "related_incidents": [],
        "runbooks": [],
        "known_issues": [],
        "previous_investigations": [],
    }
    if not investigation_id and not service_name and not ticket_key and not alert_id:
        return empty

    retriever = InvestigationGraphRetriever(client)
    service = (service_name or "").strip()

    deployments = retriever.get_related_deployments(
        investigation_id=investigation_id,
        service_name=service if not investigation_id else "",
        limit=max_items,
    )
    if not deployments and service:
        deployments = retriever.get_related_deployments(service_name=service, limit=max_items)

    alerts = retriever.get_related_alerts(
        investigation_id=investigation_id,
        service_name=service,
        limit=max_items,
    )
    incidents = retriever.get_related_incidents(
        investigation_id=investigation_id,
        alert_id=alert_id,
        service_name=service,
        limit=max_items,
    )

    known_issues: list[Any] = []
    alert_ids = [alert_id] if alert_id else [a.alert_id for a in alerts[:max_items] if a.alert_id]
    seen_known: set[str] = set()
    for aid in alert_ids:
        for issue in retriever.get_known_issues_for_alert(aid, limit=max_items):
            if issue.known_issue_id and issue.known_issue_id in seen_known:
                continue
            if issue.known_issue_id:
                seen_known.add(issue.known_issue_id)
            known_issues.append(issue)
            if len(known_issues) >= max_items:
                break
        if len(known_issues) >= max_items:
            break

    previous = retriever.get_previous_similar_investigations(
        investigation_id=investigation_id,
        service_name=service,
        ticket_key=ticket_key,
        limit=max_items,
    )

    return {
        "related_commits": [],
        "related_deployments": [_compact(d) for d in deployments[:max_items]],
        "related_alerts": [_compact(a) for a in alerts[:max_items]],
        "related_incidents": [_compact(i) for i in incidents[:max_items]],
        "runbooks": [],
        "known_issues": [_compact(k) for k in known_issues[:max_items]],
        "previous_investigations": [_compact(p) for p in previous[:max_items]],
    }
