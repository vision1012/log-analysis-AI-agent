"""
Investigation graph retriever — read-only queries over persisted MCP context.

Returns normalized retrieval objects. Does not invoke GraphRAG.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient
from graph.retrieval_models import (
    GraphAlertRecord,
    GraphCommitRecord,
    GraphDeploymentRecord,
    GraphIncidentRecord,
    GraphInvestigationRecord,
    GraphKnownIssueRecord,
    GraphRunbookRecord,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _row_str(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key)
    if value is None:
        return default
    return str(value)


def _row_int(row: dict[str, Any], key: str, default: int = 0) -> int:
    value = row.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _row_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class InvestigationGraphRetriever:
    """Read-only retrieval APIs over the MCP investigation graph."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    def get_related_deployments(
        self,
        *,
        investigation_id: str = "",
        service_name: str = "",
        limit: int | None = None,
    ) -> list[GraphDeploymentRecord]:
        """Return deployments related to an investigation and/or service."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_DEPLOYMENT_LIMIT", 20)
        if investigation_id:
            rows = self._client.execute_read(
                """
                MATCH (i:Investigation {id: $investigation_id})
                OPTIONAL MATCH (i)-[*1..10]-(d:Deployment)
                WITH DISTINCT d, i
                WHERE d IS NOT NULL
                OPTIONAL MATCH (m:MetricEvent)<-[:OBSERVED_METRIC]-(d)
                RETURN d.id AS deployment_id,
                       d.environment AS environment,
                       d.status AS status,
                       d.commit_sha AS commit_sha,
                       d.deployed_at AS deployed_at,
                       d.deployment_url AS deployment_url,
                       coalesce(m.service, '') AS service_name,
                       i.id AS investigation_id
                ORDER BY d.deployed_at DESC
                LIMIT $limit
                """,
                {"investigation_id": investigation_id, "limit": max_rows},
            )
        elif service_name:
            rows = self._client.execute_read(
                """
                MATCH (m:MetricEvent)
                WHERE toLower(m.service) = toLower($service_name)
                MATCH (d:Deployment)-[:OBSERVED_METRIC]->(m)
                RETURN DISTINCT d.id AS deployment_id,
                       d.environment AS environment,
                       d.status AS status,
                       d.commit_sha AS commit_sha,
                       d.deployed_at AS deployed_at,
                       d.deployment_url AS deployment_url,
                       m.service AS service_name,
                       '' AS investigation_id
                ORDER BY d.deployed_at DESC
                LIMIT $limit
                """,
                {"service_name": service_name, "limit": max_rows},
            )
        else:
            rows = self._client.execute_read(
                """
                MATCH (d:Deployment)
                RETURN d.id AS deployment_id,
                       d.environment AS environment,
                       d.status AS status,
                       d.commit_sha AS commit_sha,
                       d.deployed_at AS deployed_at,
                       d.deployment_url AS deployment_url,
                       '' AS service_name,
                       '' AS investigation_id
                ORDER BY d.deployed_at DESC
                LIMIT $limit
                """,
                {"limit": max_rows},
            )
        return [_deployment_from_row(row) for row in rows]

    def get_related_alerts(
        self,
        *,
        investigation_id: str = "",
        service_name: str = "",
        limit: int | None = None,
    ) -> list[GraphAlertRecord]:
        """Return monitor alerts related to an investigation or service."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_ALERT_LIMIT", 20)
        if investigation_id:
            rows = self._client.execute_read(
                """
                MATCH (i:Investigation {id: $investigation_id})
                OPTIONAL MATCH (i)-[*1..10]-(a:AlertEvent)
                WITH DISTINCT a, i
                WHERE a IS NOT NULL
                RETURN a.id AS alert_id,
                       a.title AS title,
                       a.message AS message,
                       a.severity AS severity,
                       a.service AS service,
                       a.status AS status,
                       a.triggered_at AS triggered_at,
                       a.resolved_at AS resolved_at,
                       i.id AS investigation_id
                ORDER BY a.triggered_at DESC
                LIMIT $limit
                """,
                {"investigation_id": investigation_id, "limit": max_rows},
            )
        else:
            rows = self._client.execute_read(
                """
                MATCH (a:AlertEvent)
                WHERE $service_name = '' OR toLower(a.service) = toLower($service_name)
                RETURN a.id AS alert_id,
                       a.title AS title,
                       a.message AS message,
                       a.severity AS severity,
                       a.service AS service,
                       a.status AS status,
                       a.triggered_at AS triggered_at,
                       a.resolved_at AS resolved_at,
                       '' AS investigation_id
                ORDER BY a.triggered_at DESC
                LIMIT $limit
                """,
                {"service_name": service_name, "limit": max_rows},
            )
        return [_alert_from_row(row) for row in rows]

    def get_related_incidents(
        self,
        *,
        investigation_id: str = "",
        alert_id: str = "",
        service_name: str = "",
        limit: int | None = None,
    ) -> list[GraphIncidentRecord]:
        """Return PagerDuty incidents related to alerts, services, or investigations."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_INCIDENT_LIMIT", 20)
        if investigation_id:
            rows = self._client.execute_read(
                """
                MATCH (i:Investigation {id: $investigation_id})
                OPTIONAL MATCH (i)-[*1..10]-(p:PagerDutyIncident)
                OPTIONAL MATCH (a:AlertEvent)-[:ESCALATED_TO]->(p)
                WITH DISTINCT p, a, i
                WHERE p IS NOT NULL
                RETURN p.id AS incident_id,
                       coalesce(p.incident_number, 0) AS incident_number,
                       p.title AS title,
                       p.service_name AS service_name,
                       p.urgency AS urgency,
                       p.status AS status,
                       p.created_at AS created_at,
                       p.resolved_at AS resolved_at,
                       p.html_url AS html_url,
                       coalesce(a.id, '') AS alert_id,
                       i.id AS investigation_id
                ORDER BY p.created_at DESC
                LIMIT $limit
                """,
                {"investigation_id": investigation_id, "limit": max_rows},
            )
        else:
            rows = self._client.execute_read(
                """
                MATCH (a:AlertEvent)-[:ESCALATED_TO]->(p:PagerDutyIncident)
                WHERE ($alert_id = '' OR a.id = $alert_id)
                  AND ($service_name = '' OR toLower(a.service) = toLower($service_name)
                       OR toLower(p.service_name) = toLower($service_name))
                RETURN p.id AS incident_id,
                       coalesce(p.incident_number, 0) AS incident_number,
                       p.title AS title,
                       p.service_name AS service_name,
                       p.urgency AS urgency,
                       p.status AS status,
                       p.created_at AS created_at,
                       p.resolved_at AS resolved_at,
                       p.html_url AS html_url,
                       a.id AS alert_id,
                       '' AS investigation_id
                ORDER BY p.created_at DESC
                LIMIT $limit
                """,
                {
                    "alert_id": alert_id,
                    "service_name": service_name,
                    "limit": max_rows,
                },
            )
        return [_incident_from_row(row) for row in rows]

    def get_recent_commits_for_service(
        self,
        service_name: str,
        *,
        limit: int | None = None,
    ) -> list[GraphCommitRecord]:
        """Return recent commits associated with a service via deployment/alert chain."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_COMMIT_LIMIT", 20)
        rows = self._client.execute_read(
            """
            MATCH (m:MetricEvent)
            WHERE toLower(m.service) = toLower($service_name)
            MATCH (d:Deployment)-[:OBSERVED_METRIC]->(m)
            OPTIONAL MATCH (b:Build)-[:PRODUCED_DEPLOYMENT]->(d)
            OPTIONAL MATCH (c:Commit)-[:TRIGGERED_BUILD]->(b)
            WITH DISTINCT c, m
            WHERE c IS NOT NULL
            RETURN c.sha AS sha,
                   c.message AS message,
                   c.author AS author,
                   c.committed_at AS committed_at,
                   c.repo_ref AS repo_ref,
                   m.service AS service_name
            ORDER BY c.committed_at DESC
            LIMIT $limit
            """,
            {"service_name": service_name, "limit": max_rows},
        )
        if rows:
            return [_commit_from_row(row) for row in rows]

        rows = self._client.execute_read(
            """
            MATCH (d:Deployment)
            WHERE d.commit_sha IS NOT NULL AND d.commit_sha <> ''
            OPTIONAL MATCH (a:AlertEvent {service: $service_name})
            OPTIONAL MATCH (m:MetricEvent)-[:TRIGGERED_ALERT]->(a)
            OPTIONAL MATCH (d)-[:OBSERVED_METRIC]->(m)
            WITH DISTINCT d
            MATCH (c:Commit {sha: d.commit_sha})
            RETURN c.sha AS sha,
                   c.message AS message,
                   c.author AS author,
                   c.committed_at AS committed_at,
                   c.repo_ref AS repo_ref,
                   $service_name AS service_name
            ORDER BY c.committed_at DESC
            LIMIT $limit
            """,
            {"service_name": service_name, "limit": max_rows},
        )
        return [_commit_from_row(row) for row in rows]

    def get_known_issues_for_alert(
        self,
        alert_id: str,
        *,
        limit: int | None = None,
    ) -> list[GraphKnownIssueRecord]:
        """Return known issues linked to an alert."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_KNOWN_ISSUE_LIMIT", 10)
        rows = self._client.execute_read(
            """
            MATCH (a:AlertEvent {id: $alert_id})-[:MATCHES_KNOWN_ISSUE]->(k:KnownIssue)
            RETURN k.id AS known_issue_id,
                   k.title AS title,
                   k.affected_service AS affected_service,
                   k.workaround AS workaround,
                   k.severity AS severity,
                   k.url AS url,
                   a.id AS alert_id
            ORDER BY k.updated_at DESC
            LIMIT $limit
            """,
            {"alert_id": alert_id, "limit": max_rows},
        )
        return [_known_issue_from_row(row) for row in rows]

    def get_runbooks_for_service(
        self,
        service_name: str,
        *,
        limit: int | None = None,
    ) -> list[GraphRunbookRecord]:
        """Return runbooks linked to a service."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_RUNBOOK_LIMIT", 10)
        rows = self._client.execute_read(
            """
            MATCH (s:Service {name: $service_name})-[:HAS_RUNBOOK]->(r:Runbook)
            RETURN r.id AS runbook_id,
                   r.title AS title,
                   r.service_name AS service_name,
                   r.summary AS summary,
                   r.url AS url,
                   r.space_key AS space_key,
                   r.updated_at AS updated_at
            ORDER BY r.updated_at DESC
            LIMIT $limit
            """,
            {"service_name": service_name, "limit": max_rows},
        )
        if rows:
            return [_runbook_from_row(row) for row in rows]

        rows = self._client.execute_read(
            """
            MATCH (r:Runbook)
            WHERE toLower(r.service_name) = toLower($service_name)
            RETURN r.id AS runbook_id,
                   r.title AS title,
                   r.service_name AS service_name,
                   r.summary AS summary,
                   r.url AS url,
                   r.space_key AS space_key,
                   r.updated_at AS updated_at
            ORDER BY r.updated_at DESC
            LIMIT $limit
            """,
            {"service_name": service_name, "limit": max_rows},
        )
        return [_runbook_from_row(row) for row in rows]

    def get_previous_similar_investigations(
        self,
        *,
        investigation_id: str = "",
        service_name: str = "",
        ticket_key: str = "",
        limit: int | None = None,
    ) -> list[GraphInvestigationRecord]:
        """Return prior investigations with similar ticket or service context."""
        max_rows = limit or _env_int("INVESTIGATION_GRAPH_SIMILAR_LIMIT", 10)
        rows = self._client.execute_read(
            """
            MATCH (current:Investigation)
            WHERE ($investigation_id = '' OR current.id = $investigation_id)
            WITH current
            LIMIT 1
            MATCH (other:Investigation)
            WHERE ($investigation_id = '' OR other.id <> $investigation_id)
              AND (
                ($ticket_key <> '' AND other.ticket_key = $ticket_key)
                OR ($ticket_key <> '' AND current.ticket_key <> '' AND other.ticket_key = current.ticket_key)
                OR (
                  $service_name <> ''
                  AND EXISTS {
                    MATCH (s:Service {name: $service_name})-[:HAS_RUNBOOK]->(:Runbook)
                    MATCH (other)-[:HAS_JIRA_TICKET]->(:JiraTicket)
                  }
                )
                OR (
                  current.ticket_key <> ''
                  AND other.ticket_key STARTS WITH split(current.ticket_key, '-')[0] + '-'
                  AND other.ticket_key <> current.ticket_key
                )
              )
            RETURN other.id AS investigation_id,
                   other.ticket_key AS ticket_key,
                   other.created_at AS created_at,
                   other.updated_at AS updated_at,
                   CASE
                     WHEN other.ticket_key = current.ticket_key THEN 1.0
                     WHEN other.ticket_key STARTS WITH split(current.ticket_key, '-')[0] + '-' THEN 0.7
                     ELSE 0.5
                   END AS similarity_score,
                   $service_name AS shared_service,
                   CASE
                     WHEN other.ticket_key = current.ticket_key THEN 'same_ticket_key'
                     WHEN other.ticket_key STARTS WITH split(current.ticket_key, '-')[0] + '-' THEN 'same_project'
                     WHEN $service_name <> '' THEN 'shared_service'
                     ELSE 'graph_proximity'
                   END AS match_reason
            ORDER BY similarity_score DESC, other.created_at DESC
            LIMIT $limit
            """,
            {
                "investigation_id": investigation_id,
                "service_name": service_name,
                "ticket_key": ticket_key,
                "limit": max_rows,
            },
        )
        return [_investigation_from_row(row) for row in rows]


def _deployment_from_row(row: dict[str, Any]) -> GraphDeploymentRecord:
    return GraphDeploymentRecord(
        deployment_id=_row_str(row, "deployment_id"),
        environment=_row_str(row, "environment"),
        status=_row_str(row, "status"),
        commit_sha=_row_str(row, "commit_sha"),
        deployed_at=row.get("deployed_at"),
        deployment_url=_row_str(row, "deployment_url"),
        service_name=_row_str(row, "service_name"),
        investigation_id=_row_str(row, "investigation_id"),
    )


def _alert_from_row(row: dict[str, Any]) -> GraphAlertRecord:
    return GraphAlertRecord(
        alert_id=_row_str(row, "alert_id"),
        title=_row_str(row, "title"),
        message=_row_str(row, "message"),
        severity=_row_str(row, "severity"),
        service=_row_str(row, "service"),
        status=_row_str(row, "status"),
        triggered_at=row.get("triggered_at"),
        resolved_at=row.get("resolved_at"),
        investigation_id=_row_str(row, "investigation_id"),
    )


def _incident_from_row(row: dict[str, Any]) -> GraphIncidentRecord:
    return GraphIncidentRecord(
        incident_id=_row_str(row, "incident_id"),
        incident_number=_row_int(row, "incident_number"),
        title=_row_str(row, "title"),
        service_name=_row_str(row, "service_name"),
        urgency=_row_str(row, "urgency"),
        status=_row_str(row, "status"),
        created_at=row.get("created_at"),
        resolved_at=row.get("resolved_at"),
        html_url=_row_str(row, "html_url"),
        alert_id=_row_str(row, "alert_id"),
        investigation_id=_row_str(row, "investigation_id"),
    )


def _commit_from_row(row: dict[str, Any]) -> GraphCommitRecord:
    return GraphCommitRecord(
        sha=_row_str(row, "sha"),
        message=_row_str(row, "message"),
        author=_row_str(row, "author"),
        committed_at=row.get("committed_at"),
        repo_ref=_row_str(row, "repo_ref"),
        service_name=_row_str(row, "service_name"),
    )


def _known_issue_from_row(row: dict[str, Any]) -> GraphKnownIssueRecord:
    return GraphKnownIssueRecord(
        known_issue_id=_row_str(row, "known_issue_id"),
        title=_row_str(row, "title"),
        affected_service=_row_str(row, "affected_service"),
        workaround=_row_str(row, "workaround"),
        severity=_row_str(row, "severity"),
        url=_row_str(row, "url"),
        alert_id=_row_str(row, "alert_id"),
    )


def _runbook_from_row(row: dict[str, Any]) -> GraphRunbookRecord:
    return GraphRunbookRecord(
        runbook_id=_row_str(row, "runbook_id"),
        title=_row_str(row, "title"),
        service_name=_row_str(row, "service_name"),
        summary=_row_str(row, "summary"),
        url=_row_str(row, "url"),
        space_key=_row_str(row, "space_key"),
        updated_at=row.get("updated_at"),
    )


def _investigation_from_row(row: dict[str, Any]) -> GraphInvestigationRecord:
    return GraphInvestigationRecord(
        investigation_id=_row_str(row, "investigation_id"),
        ticket_key=_row_str(row, "ticket_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        similarity_score=_row_float(row, "similarity_score"),
        shared_service=_row_str(row, "shared_service"),
        match_reason=_row_str(row, "match_reason"),
    )
