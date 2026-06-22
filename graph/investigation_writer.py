"""
Investigation graph writer — persist MCP investigation context nodes and edges.

Idempotent MERGE-based upserts. Supports atomic batch transactions.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from graph.neo4j_client import Neo4jClient
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.confluence_models import ArchitectureDocument, KnownIssueDocument, RunbookDocument
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.gitlab_models import McpDeploymentEvent, McpGitLabCommit, McpMergeRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import ContainerEvent, NodeEvent, PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent

logger = logging.getLogger(__name__)

_Op = Tuple[str, dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join((p or "").strip() for p in parts if (p or "").strip())
    if not raw:
        raw = prefix
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


class InvestigationGraphWriter:
    """Write MCP investigation entities and relationships into Neo4j."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    def _run_or_batch(self, op: _Op, batch: Optional[List[_Op]] = None) -> None:
        if batch is not None:
            batch.append(op)
        else:
            self._client.execute_write(op[0], op[1])

    def write_atomic(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        self._client.execute_write_tx(operations)

    # --- Node writers ---

    def upsert_investigation(
        self,
        investigation_id: str,
        *,
        ticket_key: str = "",
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        q = """
        MERGE (n:Investigation {id: $id})
        ON CREATE SET n.ticket_key = $ticket_key, n.created_at = $created_at
        ON MATCH SET n.ticket_key = COALESCE($ticket_key, n.ticket_key),
                     n.updated_at = $created_at
        """
        self._run_or_batch(
            (q, {"id": investigation_id, "ticket_key": ticket_key, "created_at": _utc_now()}),
            _batch,
        )

    def upsert_jira_ticket(self, ticket: McpTicketContext, *, _batch: Optional[List[_Op]] = None) -> str:
        ticket_id = (ticket.issue_key or "").strip() or _stable_id("jira", ticket.summary)
        q = """
        MERGE (n:JiraTicket {issue_key: $issue_key})
        ON CREATE SET n.summary = $summary, n.status = $status, n.priority = $priority,
                      n.url = $url, n.description = $description
        ON MATCH SET n.summary = COALESCE($summary, n.summary),
                     n.status = COALESCE($status, n.status),
                     n.priority = COALESCE($priority, n.priority),
                     n.url = COALESCE($url, n.url),
                     n.description = COALESCE($description, n.description)
        """
        self._run_or_batch(
            (
                q,
                {
                    "issue_key": ticket_id,
                    "summary": ticket.summary,
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "url": ticket.url,
                    "description": ticket.description,
                },
            ),
            _batch,
        )
        return ticket_id

    def upsert_pull_request(self, pr: McpPullRequest, *, _batch: Optional[List[_Op]] = None) -> str:
        pr_id = _stable_id("pr", str(pr.number), pr.url, pr.title)
        q = """
        MERGE (n:PullRequest {id: $id})
        ON CREATE SET n.number = $number, n.title = $title, n.state = $state,
                      n.merged = $merged, n.author = $author, n.url = $url
        ON MATCH SET n.title = COALESCE($title, n.title),
                     n.state = COALESCE($state, n.state),
                     n.merged = COALESCE($merged, n.merged)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": pr_id,
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "merged": pr.merged,
                    "author": pr.author,
                    "url": pr.url,
                },
            ),
            _batch,
        )
        return pr_id

    def upsert_merge_request(self, mr: McpMergeRequest, *, _batch: Optional[List[_Op]] = None) -> str:
        mr_id = _stable_id("mr", str(mr.iid), mr.url, mr.title)
        q = """
        MERGE (n:MergeRequest {id: $id})
        ON CREATE SET n.iid = $iid, n.title = $title, n.state = $state,
                      n.author = $author, n.url = $url
        ON MATCH SET n.title = COALESCE($title, n.title),
                     n.state = COALESCE($state, n.state)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": mr_id,
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "author": mr.author,
                    "url": mr.url,
                },
            ),
            _batch,
        )
        return mr_id

    def upsert_commit(
        self,
        sha: str,
        *,
        message: str = "",
        author: str = "",
        committed_at: str | None = None,
        repo_ref: str = "",
        _batch: Optional[List[_Op]] = None,
    ) -> str:
        commit_sha = (sha or "").strip() or _stable_id("commit", message, author)
        q = """
        MERGE (n:Commit {sha: $sha})
        ON CREATE SET n.message = $message, n.author = $author,
                      n.committed_at = $committed_at, n.repo_ref = $repo_ref
        ON MATCH SET n.message = COALESCE($message, n.message),
                     n.author = COALESCE($author, n.author),
                     n.committed_at = COALESCE($committed_at, n.committed_at),
                     n.repo_ref = COALESCE($repo_ref, n.repo_ref)
        """
        self._run_or_batch(
            (
                q,
                {
                    "sha": commit_sha,
                    "message": message,
                    "author": author,
                    "committed_at": committed_at,
                    "repo_ref": repo_ref,
                },
            ),
            _batch,
        )
        return commit_sha

    def upsert_build(self, build: BuildEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        build_id = (build.build_id or "").strip() or _stable_id(
            "build", str(build.build_number), build.commit_sha, build.branch
        )
        q = """
        MERGE (n:Build {id: $id})
        ON CREATE SET n.build_number = $build_number, n.status = $status,
                      n.branch = $branch, n.commit_sha = $commit_sha,
                      n.build_url = $build_url, n.started_at = $started_at,
                      n.completed_at = $completed_at
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.commit_sha = COALESCE($commit_sha, n.commit_sha)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": build_id,
                    "build_number": build.build_number,
                    "status": build.status,
                    "branch": build.branch,
                    "commit_sha": build.commit_sha,
                    "build_url": build.build_url,
                    "started_at": build.started_at,
                    "completed_at": build.completed_at,
                },
            ),
            _batch,
        )
        return build_id

    def upsert_deployment(
        self,
        *,
        deployment_id: str,
        environment: str = "",
        status: str = "",
        commit_sha: str = "",
        deployed_at: str | None = None,
        deployment_url: str = "",
        _batch: Optional[List[_Op]] = None,
    ) -> str:
        dep_id = (deployment_id or "").strip() or _stable_id("deployment", environment, commit_sha, deployed_at or "")
        q = """
        MERGE (n:Deployment {id: $id})
        ON CREATE SET n.environment = $environment, n.status = $status,
                      n.commit_sha = $commit_sha, n.deployed_at = $deployed_at,
                      n.deployment_url = $deployment_url
        ON MATCH SET n.environment = COALESCE($environment, n.environment),
                     n.status = COALESCE($status, n.status),
                     n.commit_sha = COALESCE($commit_sha, n.commit_sha),
                     n.deployed_at = COALESCE($deployed_at, n.deployed_at)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": dep_id,
                    "environment": environment,
                    "status": status,
                    "commit_sha": commit_sha,
                    "deployed_at": deployed_at,
                    "deployment_url": deployment_url,
                },
            ),
            _batch,
        )
        return dep_id

    def upsert_metric_event(self, metric: MetricEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        metric_id = _stable_id("metric", metric.metric_name, metric.service, metric.timestamp or "")
        q = """
        MERGE (n:MetricEvent {id: $id})
        ON CREATE SET n.metric_name = $metric_name, n.service = $service,
                      n.value = $value, n.unit = $unit, n.severity = $severity,
                      n.timestamp = $timestamp
        ON MATCH SET n.value = COALESCE($value, n.value),
                     n.severity = COALESCE($severity, n.severity)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": metric_id,
                    "metric_name": metric.metric_name,
                    "service": metric.service,
                    "value": metric.value,
                    "unit": metric.unit,
                    "severity": metric.severity,
                    "timestamp": metric.timestamp,
                },
            ),
            _batch,
        )
        return metric_id

    def upsert_alert_event(self, alert: AlertEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        alert_id = (alert.alert_id or "").strip() or _stable_id("alert", alert.title, alert.service, alert.triggered_at or "")
        q = """
        MERGE (n:AlertEvent {id: $id})
        ON CREATE SET n.title = $title, n.message = $message, n.severity = $severity,
                      n.service = $service, n.status = $status,
                      n.triggered_at = $triggered_at, n.resolved_at = $resolved_at
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.severity = COALESCE($severity, n.severity)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": alert_id,
                    "title": alert.title,
                    "message": alert.message,
                    "severity": alert.severity,
                    "service": alert.service,
                    "status": alert.status,
                    "triggered_at": alert.triggered_at,
                    "resolved_at": alert.resolved_at,
                },
            ),
            _batch,
        )
        return alert_id

    def upsert_trace_event(self, trace: TraceEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        trace_id = (trace.trace_id or "").strip() or _stable_id("trace", trace.service, trace.endpoint, trace.timestamp or "")
        q = """
        MERGE (n:TraceEvent {id: $id})
        ON CREATE SET n.service = $service, n.endpoint = $endpoint,
                      n.latency_ms = $latency_ms, n.error_count = $error_count,
                      n.timestamp = $timestamp
        ON MATCH SET n.latency_ms = COALESCE($latency_ms, n.latency_ms),
                     n.error_count = COALESCE($error_count, n.error_count)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": trace_id,
                    "service": trace.service,
                    "endpoint": trace.endpoint,
                    "latency_ms": trace.latency_ms,
                    "error_count": trace.error_count,
                    "timestamp": trace.timestamp,
                },
            ),
            _batch,
        )
        return trace_id

    def upsert_pod(self, pod: PodEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        pod_id = _stable_id("pod", pod.namespace, pod.pod_name)
        q = """
        MERGE (n:Pod {id: $id})
        ON CREATE SET n.pod_name = $pod_name, n.namespace = $namespace,
                      n.node_name = $node_name, n.status = $status,
                      n.restart_count = $restart_count, n.reason = $reason,
                      n.timestamp = $timestamp
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.restart_count = COALESCE($restart_count, n.restart_count),
                     n.reason = COALESCE($reason, n.reason)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": pod_id,
                    "pod_name": pod.pod_name,
                    "namespace": pod.namespace,
                    "node_name": pod.node_name,
                    "status": pod.status,
                    "restart_count": pod.restart_count,
                    "reason": pod.reason,
                    "timestamp": pod.timestamp,
                },
            ),
            _batch,
        )
        return pod_id

    def upsert_container(self, container: ContainerEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        container_id = _stable_id("container", container.pod_name, container.container_name)
        q = """
        MERGE (n:Container {id: $id})
        ON CREATE SET n.container_name = $container_name, n.pod_name = $pod_name,
                      n.image = $image, n.status = $status, n.reason = $reason,
                      n.timestamp = $timestamp
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.reason = COALESCE($reason, n.reason)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": container_id,
                    "container_name": container.container_name,
                    "pod_name": container.pod_name,
                    "image": container.image,
                    "status": container.status,
                    "reason": container.reason,
                    "timestamp": container.timestamp,
                },
            ),
            _batch,
        )
        return container_id

    def upsert_node(self, node: NodeEvent, *, _batch: Optional[List[_Op]] = None) -> str:
        node_id = (node.node_name or "").strip() or _stable_id("node", node.status)
        q = """
        MERGE (n:Node {id: $id})
        ON CREATE SET n.node_name = $node_name, n.status = $status,
                      n.cpu_usage = $cpu_usage, n.memory_usage = $memory_usage,
                      n.timestamp = $timestamp
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.cpu_usage = COALESCE($cpu_usage, n.cpu_usage),
                     n.memory_usage = COALESCE($memory_usage, n.memory_usage)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": node_id,
                    "node_name": node.node_name,
                    "status": node.status,
                    "cpu_usage": node.cpu_usage,
                    "memory_usage": node.memory_usage,
                    "timestamp": node.timestamp,
                },
            ),
            _batch,
        )
        return node_id

    def upsert_pagerduty_incident(
        self, incident: PagerDutyIncidentEvent, *, _batch: Optional[List[_Op]] = None
    ) -> str:
        incident_id = (incident.incident_id or "").strip() or _stable_id(
            "pd", str(incident.incident_number), incident.title
        )
        q = """
        MERGE (n:PagerDutyIncident {id: $id})
        ON CREATE SET n.incident_number = $incident_number, n.title = $title,
                      n.description = $description, n.service_name = $service_name,
                      n.urgency = $urgency, n.status = $status,
                      n.created_at = $created_at, n.resolved_at = $resolved_at,
                      n.html_url = $html_url
        ON MATCH SET n.status = COALESCE($status, n.status),
                     n.urgency = COALESCE($urgency, n.urgency)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": incident_id,
                    "incident_number": incident.incident_number,
                    "title": incident.title,
                    "description": incident.description,
                    "service_name": incident.service_name,
                    "urgency": incident.urgency,
                    "status": incident.status,
                    "created_at": incident.created_at,
                    "resolved_at": incident.resolved_at,
                    "html_url": incident.html_url,
                },
            ),
            _batch,
        )
        return incident_id

    def upsert_runbook(self, doc: RunbookDocument, *, _batch: Optional[List[_Op]] = None) -> str:
        doc_id = (doc.document_id or "").strip() or _stable_id("runbook", doc.title, doc.space_key)
        q = """
        MERGE (n:Runbook {id: $id})
        ON CREATE SET n.title = $title, n.space_key = $space_key, n.url = $url,
                      n.service_name = $service_name, n.summary = $summary,
                      n.content_excerpt = $content_excerpt, n.updated_at = $updated_at
        ON MATCH SET n.title = COALESCE($title, n.title),
                     n.summary = COALESCE($summary, n.summary),
                     n.updated_at = COALESCE($updated_at, n.updated_at)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": doc_id,
                    "title": doc.title,
                    "space_key": doc.space_key,
                    "url": doc.url,
                    "service_name": doc.service_name,
                    "summary": doc.summary,
                    "content_excerpt": doc.content_excerpt,
                    "updated_at": doc.updated_at,
                },
            ),
            _batch,
        )
        return doc_id

    def upsert_known_issue(self, doc: KnownIssueDocument, *, _batch: Optional[List[_Op]] = None) -> str:
        doc_id = (doc.document_id or "").strip() or _stable_id("known_issue", doc.title, doc.affected_service)
        q = """
        MERGE (n:KnownIssue {id: $id})
        ON CREATE SET n.title = $title, n.space_key = $space_key, n.url = $url,
                      n.affected_service = $affected_service, n.workaround = $workaround,
                      n.severity = $severity, n.updated_at = $updated_at
        ON MATCH SET n.workaround = COALESCE($workaround, n.workaround),
                     n.severity = COALESCE($severity, n.severity),
                     n.updated_at = COALESCE($updated_at, n.updated_at)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": doc_id,
                    "title": doc.title,
                    "space_key": doc.space_key,
                    "url": doc.url,
                    "affected_service": doc.affected_service,
                    "workaround": doc.workaround,
                    "severity": doc.severity,
                    "updated_at": doc.updated_at,
                },
            ),
            _batch,
        )
        return doc_id

    def upsert_architecture_document(
        self, doc: ArchitectureDocument, *, _batch: Optional[List[_Op]] = None
    ) -> str:
        doc_id = (doc.document_id or "").strip() or _stable_id("architecture", doc.title, doc.service_name)
        q = """
        MERGE (n:ArchitectureDocument {id: $id})
        ON CREATE SET n.title = $title, n.space_key = $space_key, n.url = $url,
                      n.service_name = $service_name, n.summary = $summary,
                      n.updated_at = $updated_at
        ON MATCH SET n.title = COALESCE($title, n.title),
                     n.summary = COALESCE($summary, n.summary),
                     n.updated_at = COALESCE($updated_at, n.updated_at)
        """
        self._run_or_batch(
            (
                q,
                {
                    "id": doc_id,
                    "title": doc.title,
                    "space_key": doc.space_key,
                    "url": doc.url,
                    "service_name": doc.service_name,
                    "summary": doc.summary,
                    "updated_at": doc.updated_at,
                },
            ),
            _batch,
        )
        return doc_id

    def upsert_service(self, service_name: str, *, _batch: Optional[List[_Op]] = None) -> str:
        name = (service_name or "").strip() or "unknown-service"
        q = """
        MERGE (n:Service {name: $name})
        ON CREATE SET n.created_at = $created_at
        ON MATCH SET n.updated_at = $created_at
        """
        self._run_or_batch((q, {"name": name, "created_at": _utc_now()}), _batch)
        return name

    # --- Relationship writers ---

    def link_investigation_jira_ticket(
        self, investigation_id: str, issue_key: str, *, _batch: Optional[List[_Op]] = None
    ) -> None:
        q = """
        MATCH (i:Investigation {id: $investigation_id})
        MATCH (t:JiraTicket {issue_key: $issue_key})
        MERGE (i)-[:HAS_JIRA_TICKET]->(t)
        """
        self._run_or_batch((q, {"investigation_id": investigation_id, "issue_key": issue_key}), _batch)

    def link_pull_request_commit(
        self, pr_id: str, commit_sha: str, *, _batch: Optional[List[_Op]] = None
    ) -> None:
        q = """
        MATCH (pr:PullRequest {id: $pr_id})
        MATCH (c:Commit {sha: $commit_sha})
        MERGE (pr)-[:HAS_COMMIT]->(c)
        """
        self._run_or_batch((q, {"pr_id": pr_id, "commit_sha": commit_sha}), _batch)

    def link_commit_build(self, commit_sha: str, build_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (c:Commit {sha: $commit_sha})
        MATCH (b:Build {id: $build_id})
        MERGE (c)-[:TRIGGERED_BUILD]->(b)
        """
        self._run_or_batch((q, {"commit_sha": commit_sha, "build_id": build_id}), _batch)

    def link_build_deployment(self, build_id: str, deployment_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (b:Build {id: $build_id})
        MATCH (d:Deployment {id: $deployment_id})
        MERGE (b)-[:PRODUCED_DEPLOYMENT]->(d)
        """
        self._run_or_batch((q, {"build_id": build_id, "deployment_id": deployment_id}), _batch)

    def link_deployment_metric(
        self, deployment_id: str, metric_id: str, *, _batch: Optional[List[_Op]] = None
    ) -> None:
        q = """
        MATCH (d:Deployment {id: $deployment_id})
        MATCH (m:MetricEvent {id: $metric_id})
        MERGE (d)-[:OBSERVED_METRIC]->(m)
        """
        self._run_or_batch((q, {"deployment_id": deployment_id, "metric_id": metric_id}), _batch)

    def link_metric_alert(self, metric_id: str, alert_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (m:MetricEvent {id: $metric_id})
        MATCH (a:AlertEvent {id: $alert_id})
        MERGE (m)-[:TRIGGERED_ALERT]->(a)
        """
        self._run_or_batch((q, {"metric_id": metric_id, "alert_id": alert_id}), _batch)

    def link_alert_pagerduty_incident(
        self, alert_id: str, incident_id: str, *, _batch: Optional[List[_Op]] = None
    ) -> None:
        q = """
        MATCH (a:AlertEvent {id: $alert_id})
        MATCH (p:PagerDutyIncident {id: $incident_id})
        MERGE (a)-[:ESCALATED_TO]->(p)
        """
        self._run_or_batch((q, {"alert_id": alert_id, "incident_id": incident_id}), _batch)

    def link_deployment_pod(self, deployment_id: str, pod_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (d:Deployment {id: $deployment_id})
        MATCH (p:Pod {id: $pod_id})
        MERGE (d)-[:AFFECTED_POD]->(p)
        """
        self._run_or_batch((q, {"deployment_id": deployment_id, "pod_id": pod_id}), _batch)

    def link_pod_container(self, pod_id: str, container_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (p:Pod {id: $pod_id})
        MATCH (c:Container {id: $container_id})
        MERGE (p)-[:HAS_CONTAINER]->(c)
        """
        self._run_or_batch((q, {"pod_id": pod_id, "container_id": container_id}), _batch)

    def link_pod_node(self, pod_id: str, node_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (p:Pod {id: $pod_id})
        MATCH (n:Node {id: $node_id})
        MERGE (p)-[:RUNS_ON]->(n)
        """
        self._run_or_batch((q, {"pod_id": pod_id, "node_id": node_id}), _batch)

    def link_service_runbook(self, service_name: str, runbook_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (s:Service {name: $service_name})
        MATCH (r:Runbook {id: $runbook_id})
        MERGE (s)-[:HAS_RUNBOOK]->(r)
        """
        self._run_or_batch((q, {"service_name": service_name, "runbook_id": runbook_id}), _batch)

    def link_alert_known_issue(self, alert_id: str, known_issue_id: str, *, _batch: Optional[List[_Op]] = None) -> None:
        q = """
        MATCH (a:AlertEvent {id: $alert_id})
        MATCH (k:KnownIssue {id: $known_issue_id})
        MERGE (a)-[:MATCHES_KNOWN_ISSUE]->(k)
        """
        self._run_or_batch((q, {"alert_id": alert_id, "known_issue_id": known_issue_id}), _batch)

    def link_service_architecture_document(
        self, service_name: str, architecture_id: str, *, _batch: Optional[List[_Op]] = None
    ) -> None:
        q = """
        MATCH (s:Service {name: $service_name})
        MATCH (a:ArchitectureDocument {id: $architecture_id})
        MERGE (s)-[:HAS_ARCHITECTURE_DOC]->(a)
        """
        self._run_or_batch((q, {"service_name": service_name, "architecture_id": architecture_id}), _batch)

    def write_investigation_context(
        self,
        investigation_id: str,
        context: UnifiedInvestigationContext,
        *,
        ticket_key: str = "",
    ) -> dict[str, int]:
        """Persist all MCP entities and chain relationships in one atomic transaction."""
        batch: list[_Op] = []
        counts = {
            "nodes": 0,
            "relationships": 0,
        }

        self.upsert_investigation(investigation_id, ticket_key=ticket_key, _batch=batch)
        counts["nodes"] += 1

        ticket_key_ref = ""
        if context.ticket_context:
            ticket_key_ref = self.upsert_jira_ticket(context.ticket_context, _batch=batch)
            counts["nodes"] += 1
            self.link_investigation_jira_ticket(investigation_id, ticket_key_ref, _batch=batch)
            counts["relationships"] += 1

        commit_shas: list[str] = []
        for commit in context.commits:
            if isinstance(commit, McpCommit):
                sha = self.upsert_commit(
                    commit.sha,
                    message=commit.message,
                    author=commit.author,
                    committed_at=commit.committed_at,
                    _batch=batch,
                )
            else:
                sha = self.upsert_commit(
                    commit.id,
                    message=commit.title,
                    author=commit.author,
                    committed_at=commit.committed_at,
                    _batch=batch,
                )
            commit_shas.append(sha)
            counts["nodes"] += 1

        pr_ids: list[str] = []
        for pr in context.pull_requests:
            pr_id = self.upsert_pull_request(pr, _batch=batch)
            pr_ids.append(pr_id)
            counts["nodes"] += 1
            for sha in commit_shas[:3]:
                self.link_pull_request_commit(pr_id, sha, _batch=batch)
                counts["relationships"] += 1

        for mr in context.merge_requests:
            self.upsert_merge_request(mr, _batch=batch)
            counts["nodes"] += 1

        build_ids: list[str] = []
        for build in context.build_events:
            build_id = self.upsert_build(build, _batch=batch)
            build_ids.append(build_id)
            counts["nodes"] += 1
            if build.commit_sha:
                self.link_commit_build(build.commit_sha, build_id, _batch=batch)
                counts["relationships"] += 1

        deployment_ids: list[str] = []
        for dep in context.deployment_events:
            if isinstance(dep, DeploymentEvent):
                dep_id = self.upsert_deployment(
                    deployment_id=dep.deployment_id,
                    environment=dep.environment,
                    status=dep.status,
                    commit_sha=dep.commit_sha,
                    deployed_at=dep.deployed_at,
                    deployment_url=dep.deployment_url,
                    _batch=batch,
                )
            else:
                dep_id = self.upsert_deployment(
                    deployment_id=_stable_id("gitlab-dep", dep.environment, dep.commit_sha, dep.deployed_at or ""),
                    environment=dep.environment,
                    status=dep.status,
                    commit_sha=dep.commit_sha,
                    deployed_at=dep.deployed_at,
                    deployment_url=dep.url,
                    _batch=batch,
                )
            deployment_ids.append(dep_id)
            counts["nodes"] += 1

        for build_id in build_ids:
            for dep_id in deployment_ids[:1]:
                self.link_build_deployment(build_id, dep_id, _batch=batch)
                counts["relationships"] += 1

        metric_ids: list[str] = []
        for metric in context.metric_events:
            metric_id = self.upsert_metric_event(metric, _batch=batch)
            metric_ids.append(metric_id)
            counts["nodes"] += 1
            for dep_id in deployment_ids[:1]:
                self.link_deployment_metric(dep_id, metric_id, _batch=batch)
                counts["relationships"] += 1

        alert_ids: list[str] = []
        for alert in context.alert_events:
            alert_id = self.upsert_alert_event(alert, _batch=batch)
            alert_ids.append(alert_id)
            counts["nodes"] += 1
            for metric_id in metric_ids[:1]:
                self.link_metric_alert(metric_id, alert_id, _batch=batch)
                counts["relationships"] += 1

        for trace in context.trace_events:
            self.upsert_trace_event(trace, _batch=batch)
            counts["nodes"] += 1

        pod_ids: list[str] = []
        pod_id_by_name: dict[str, str] = {}
        for pod in context.pod_events:
            pod_id = self.upsert_pod(pod, _batch=batch)
            pod_ids.append(pod_id)
            if pod.pod_name:
                pod_id_by_name[pod.pod_name] = pod_id
            counts["nodes"] += 1
            for dep_id in deployment_ids[:1]:
                self.link_deployment_pod(dep_id, pod_id, _batch=batch)
                counts["relationships"] += 1
            if pod.node_name:
                node_id = self.upsert_node(
                    NodeEvent(node_name=pod.node_name, status="", cpu_usage=0.0, memory_usage=0.0),
                    _batch=batch,
                )
                counts["nodes"] += 1
                self.link_pod_node(pod_id, node_id, _batch=batch)
                counts["relationships"] += 1

        for container in context.container_events:
            container_id = self.upsert_container(container, _batch=batch)
            counts["nodes"] += 1
            pod_id = pod_id_by_name.get(container.pod_name) or _stable_id(
                "pod", "", container.pod_name
            )
            self.link_pod_container(pod_id, container_id, _batch=batch)
            counts["relationships"] += 1

        for node in context.node_events:
            self.upsert_node(node, _batch=batch)
            counts["nodes"] += 1

        incident_ids: list[str] = []
        for incident in context.pagerduty_incidents:
            incident_id = self.upsert_pagerduty_incident(incident, _batch=batch)
            incident_ids.append(incident_id)
            counts["nodes"] += 1
            for alert_id in alert_ids[:1]:
                self.link_alert_pagerduty_incident(alert_id, incident_id, _batch=batch)
                counts["relationships"] += 1

        for doc in context.runbook_documents:
            runbook_id = self.upsert_runbook(doc, _batch=batch)
            counts["nodes"] += 1
            service = doc.service_name or ticket_key
            if service:
                self.upsert_service(service, _batch=batch)
                counts["nodes"] += 1
                self.link_service_runbook(service, runbook_id, _batch=batch)
                counts["relationships"] += 1

        for doc in context.known_issue_documents:
            known_id = self.upsert_known_issue(doc, _batch=batch)
            counts["nodes"] += 1
            for alert_id in alert_ids[:1]:
                self.link_alert_known_issue(alert_id, known_id, _batch=batch)
                counts["relationships"] += 1

        for doc in context.architecture_documents:
            arch_id = self.upsert_architecture_document(doc, _batch=batch)
            counts["nodes"] += 1
            service = doc.service_name or ticket_key
            if service:
                self.upsert_service(service, _batch=batch)
                counts["nodes"] += 1
                self.link_service_architecture_document(service, arch_id, _batch=batch)
                counts["relationships"] += 1

        if batch:
            self.write_atomic(batch)
            logger.info(
                "investigation_graph.write investigation_id=%s nodes=%d relationships=%d",
                investigation_id,
                counts["nodes"],
                counts["relationships"],
            )
        return counts
