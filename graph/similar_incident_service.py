"""
Similar incident search over the MCP investigation graph.

Uses relationship-based Neo4j traversals (no vector search).
Does not modify RCA or GraphRAG behavior.
"""

from __future__ import annotations

import os
from typing import Any

from graph.graph_visualization_service import investigation_exists
from graph.neo4j_client import Neo4jClient
from graph.retrieval_models import SimilarInvestigation
from feedback.feedback_learning_service import get_feedback_by_investigation_ids
from feedback.feedback_models import HistoricalFeedback

FACTOR_WEIGHTS: dict[str, float] = {
    "service_match": 0.12,
    "deployment_match": 0.10,
    "alert_match": 0.12,
    "known_issue_match": 0.14,
    "root_cause_match": 0.15,
    "commit_match": 0.10,
    "build_match": 0.08,
    "pagerduty_incident_match": 0.10,
    "runbook_match": 0.09,
    "pod_match": 0.10,
    "container_match": 0.10,
    "node_match": 0.10,
    "kubernetes_signal_match": 0.12,
}

FACTOR_PREFIXES: dict[str, str] = {
    "Service": "service_match",
    "Deployment": "deployment_match",
    "AlertEvent": "alert_match",
    "KnownIssue": "known_issue_match",
    "Commit": "commit_match",
    "Build": "build_match",
    "PagerDutyIncident": "pagerduty_incident_match",
    "Runbook": "runbook_match",
    "Pod": "pod_match",
    "Container": "container_match",
    "Node": "node_match",
    "K8sSignal": "kubernetes_signal_match",
}

KUBERNETES_ENTITY_FACTORS = frozenset({"pod_match", "container_match", "node_match"})

HIGH_RESTART_COUNT_THRESHOLD = 3

KUBERNETES_SIGNAL_KEYS: tuple[str, ...] = (
    "K8sSignal:CrashLoopBackOff",
    "K8sSignal:OOMKilled",
    "K8sSignal:ContainerRestart",
    "K8sSignal:HighRestartCount",
    "K8sSignal:ImagePullFailure",
    "K8sSignal:NodePressure",
    "K8sSignal:NodeMemoryPressure",
    "K8sSignal:NodeDiskPressure",
    "K8sSignal:FailedScheduling",
    "K8sSignal:ContainerFailure",
)

K8S_SIGNAL_EXPLANATIONS: dict[str, str] = {
    "K8sSignal:OOMKilled": "recurring Kubernetes OOMKilled events",
    "K8sSignal:CrashLoopBackOff": "recurring Kubernetes CrashLoopBackOff events",
    "K8sSignal:ContainerRestart": "recurring Kubernetes container restarts",
    "K8sSignal:HighRestartCount": "recurring Kubernetes high restart counts",
    "K8sSignal:ImagePullFailure": "recurring Kubernetes image pull failures",
    "K8sSignal:NodePressure": "recurring Kubernetes node pressure events",
    "K8sSignal:NodeMemoryPressure": "recurring Kubernetes node memory pressure events",
    "K8sSignal:NodeDiskPressure": "recurring Kubernetes node disk pressure events",
    "K8sSignal:FailedScheduling": "recurring Kubernetes failed scheduling events",
    "K8sSignal:ContainerFailure": "recurring Kubernetes container failures",
}

K8S_SIGNAL_EXPLANATION_PRIORITY: tuple[str, ...] = (
    "K8sSignal:OOMKilled",
    "K8sSignal:CrashLoopBackOff",
    "K8sSignal:HighRestartCount",
    "K8sSignal:ContainerRestart",
    "K8sSignal:ImagePullFailure",
    "K8sSignal:FailedScheduling",
    "K8sSignal:NodeMemoryPressure",
    "K8sSignal:NodeDiskPressure",
    "K8sSignal:NodePressure",
    "K8sSignal:ContainerFailure",
)

_IMAGE_PULL_REASONS = frozenset({"ErrImagePull", "ImagePullBackOff", "ImagePullFailure"})

_NODE_PRESSURE_STATUSES = frozenset(
    {
        "MemoryPressure",
        "DiskPressure",
        "PIDPressure",
        "NotReady",
        "Pressure",
    }
)

_CONTAINER_FAILURE_REASONS = frozenset({"Error", "Failed", "CrashLoopBackOff"})

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
TRAVERSAL_MAX_HOPS = 10


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _score_shared_keys(shared_keys: list[str], *, root_cause_overlap: bool) -> tuple[float, list[str]]:
    matched: list[str] = []
    score = 0.0
    seen_factors: set[str] = set()

    for key in shared_keys:
        if not key or ":" not in key:
            continue
        label = key.split(":", 1)[0]
        factor = FACTOR_PREFIXES.get(label)
        if not factor or factor in seen_factors:
            continue
        seen_factors.add(factor)
        matched.append(factor)
        score += FACTOR_WEIGHTS.get(factor, 0.0)

    if root_cause_overlap and "root_cause_match" not in seen_factors:
        matched.append("root_cause_match")
        score += FACTOR_WEIGHTS["root_cause_match"]

    return (round(min(1.0, score), 4), matched)


def _compute_kubernetes_similarity_score(
    matched_factors: list[str],
    shared_keys: list[str],
) -> float:
    """Kubernetes-only similarity contribution (Pod/Container/Node entities + failure signals)."""
    score = 0.0
    for factor in matched_factors:
        if factor in KUBERNETES_ENTITY_FACTORS or factor == "kubernetes_signal_match":
            score += FACTOR_WEIGHTS.get(factor, 0.0)

    signal_keys = {key for key in shared_keys if key.startswith("K8sSignal:")}
    if signal_keys and "kubernetes_signal_match" not in matched_factors:
        score += FACTOR_WEIGHTS["kubernetes_signal_match"]

    return round(min(1.0, score), 4)


def _build_match_explanation(matched_factors: list[str], shared_keys: list[str]) -> str:
    shared_set = set(shared_keys)
    for signal_key in K8S_SIGNAL_EXPLANATION_PRIORITY:
        if signal_key in shared_set:
            detail = K8S_SIGNAL_EXPLANATIONS.get(signal_key, signal_key.replace("K8sSignal:", ""))
            return f"Historical investigation matched due to {detail}"

    for key in shared_keys:
        if key.startswith("K8sSignal:"):
            detail = K8S_SIGNAL_EXPLANATIONS.get(key, key.replace("K8sSignal:", ""))
            return f"Historical investigation matched due to {detail}"

    if "pod_match" in matched_factors:
        return "Historical investigation matched due to shared Pod workload (PodEvent)"
    if "container_match" in matched_factors:
        return "Historical investigation matched due to shared Container workload (ContainerEvent)"
    if "node_match" in matched_factors:
        return "Historical investigation matched due to shared Node infrastructure (NodeEvent)"
    if "alert_match" in matched_factors:
        return "Historical investigation matched due to shared AlertEvent"
    if "deployment_match" in matched_factors:
        return "Historical investigation matched due to shared Deployment"
    if "known_issue_match" in matched_factors:
        return "Historical investigation matched due to shared KnownIssue"
    if "commit_match" in matched_factors:
        return "Historical investigation matched due to shared Commit"
    if "root_cause_match" in matched_factors:
        return "Historical investigation matched due to overlapping root-cause file paths"
    return ""


def _kubernetes_signal_key(label: str, props: dict[str, Any]) -> str | None:
    """
    Derive a shared Kubernetes failure signal key from PodEvent / ContainerEvent / NodeEvent graph props.

    Mirrors the Cypher signal CASE in find_similar_investigations.
    """
    reason = str(props.get("reason") or "").strip()
    status = str(props.get("status") or "").strip()
    restart_count = int(props.get("restart_count") or 0)

    if label == "Pod":
        if reason == "CrashLoopBackOff":
            return "K8sSignal:CrashLoopBackOff"
        if reason == "OOMKilled":
            return "K8sSignal:OOMKilled"
        if reason == "FailedScheduling":
            return "K8sSignal:FailedScheduling"
        if reason in _IMAGE_PULL_REASONS:
            return "K8sSignal:ImagePullFailure"
        if restart_count >= HIGH_RESTART_COUNT_THRESHOLD:
            return "K8sSignal:HighRestartCount"
        if restart_count > 0:
            return "K8sSignal:ContainerRestart"
    elif label == "Container":
        if reason == "CrashLoopBackOff":
            return "K8sSignal:CrashLoopBackOff"
        if reason == "OOMKilled":
            return "K8sSignal:OOMKilled"
        if reason in _IMAGE_PULL_REASONS:
            return "K8sSignal:ImagePullFailure"
        if reason in _CONTAINER_FAILURE_REASONS or status.lower() == "terminated":
            return "K8sSignal:ContainerFailure"
    elif label == "Node":
        if status == "MemoryPressure":
            return "K8sSignal:NodeMemoryPressure"
        if status == "DiskPressure":
            return "K8sSignal:NodeDiskPressure"
        if status in _NODE_PRESSURE_STATUSES or "pressure" in status.lower():
            return "K8sSignal:NodePressure"
    return None


def _shared_entity_key(label: str, props: dict[str, Any]) -> str | None:
    """Build entity shared-factor key for a graph node label and properties."""
    if label == "Service":
        name = str(props.get("name") or "").strip()
        return f"Service:{name}" if name else None
    if label == "Commit":
        sha = str(props.get("sha") or "").strip()
        return f"Commit:{sha}" if sha else None
    if label in {"Deployment", "AlertEvent", "KnownIssue", "Build", "PagerDutyIncident", "Runbook", "Pod", "Container"}:
        node_id = str(props.get("id") or "").strip()
        return f"{label}:{node_id}" if node_id else None
    if label == "Node":
        node_id = str(props.get("id") or props.get("node_name") or "").strip()
        return f"Node:{node_id}" if node_id else None
    return None


def _get_investigation_store():
    from artifacts.investigation_store import LocalFileInvestigationStore

    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        "jira_rca_investigations",
    )
    return LocalFileInvestigationStore(base)


def _file_paths_for_investigation(investigation_id: str) -> set[str]:
    try:
        record = _get_investigation_store().get_record(investigation_id) or {}
    except Exception:
        return set()

    paths: set[str] = set()
    bundle = record.get("relationship_ready_bundle") or {}
    target = str(bundle.get("rca_target_file") or "").strip()
    if target:
        paths.add(target)

    for container_key in ("future_graph_links", "derived_signals_snapshot"):
        container = record.get(container_key) or {}
        if not isinstance(container, dict):
            continue
        for path_key in ("files", "file_paths"):
            values = container.get(path_key) or []
            if isinstance(values, list):
                paths.update(str(v).strip() for v in values if str(v).strip())

    merged = (record.get("derived_signals_snapshot") or {}).get("merged") or {}
    if isinstance(merged, dict):
        for value in merged.get("file_paths") or []:
            text = str(value).strip()
            if text:
                paths.add(text)
    return paths


def _feedback_to_historical(records: list) -> list[HistoricalFeedback]:
    return [
        HistoricalFeedback(
            feedback_id=r.feedback_id,
            candidate_id=r.candidate_id,
            feedback_type=r.feedback_type,
            comments=r.comments,
            user_id=r.user_id,
            created_at=r.created_at,
            override_candidate_id=r.override_candidate_id,
        )
        for r in records
    ]


def _enrich_similar_investigation(
    item: SimilarInvestigation,
    *,
    shared_keys: list[str],
    store_record: dict[str, Any] | None,
    historical_feedback: list[HistoricalFeedback] | None = None,
) -> SimilarInvestigation:
    root_cause = item.root_cause
    confidence = item.confidence
    resolution_summary = item.resolution_summary

    for key in shared_keys:
        if key.startswith("KnownIssue:"):
            root_cause = root_cause or f"Known issue {key.split(':', 1)[1]}"
            break

    if store_record:
        bundle = store_record.get("relationship_ready_bundle") or {}
        if not root_cause:
            root_cause = str(bundle.get("rca_target_file") or "").strip()
        if not root_cause:
            files = (store_record.get("future_graph_links") or {}).get("files") or []
            if isinstance(files, list) and files:
                root_cause = str(files[0])

        ticket_summary = str(store_record.get("ticket_summary") or "").strip()
        run_status = str(store_record.get("run_status") or "").strip()
        if ticket_summary and run_status:
            resolution_summary = f"{ticket_summary} — status: {run_status}"
        elif ticket_summary:
            resolution_summary = ticket_summary

        if run_status == "completed" and confidence <= 0:
            confidence = round(min(0.95, item.similarity_score), 4)

    match_explanation = item.match_explanation
    if match_explanation and resolution_summary and match_explanation not in resolution_summary:
        resolution_summary = f"{match_explanation}. {resolution_summary}"
    elif match_explanation and not resolution_summary:
        resolution_summary = match_explanation

    return item.model_copy(
        update={
            "root_cause": root_cause,
            "confidence": confidence,
            "resolution_summary": resolution_summary,
            "historical_feedback": historical_feedback or [],
        }
    )


def find_similar_investigations(
    client: Neo4jClient,
    investigation_id: str,
    *,
    limit: int | None = None,
) -> list[SimilarInvestigation]:
    """
    Find historical investigations similar to the given investigation.

    Similarity is computed from shared graph entities reachable via relationships
    (service, deployment, alert, known issue, commit, build, PagerDuty incident, runbook,
    Kubernetes Pod/Container/Node from PodEvent/ContainerEvent/NodeEvent, and shared
    Kubernetes failure signals) plus optional root-cause file-path overlap from persisted
    investigation records.
    """
    if not investigation_exists(client, investigation_id):
        return []

    max_rows = _clamp_limit(limit)
    current_paths = _file_paths_for_investigation(investigation_id)

    rows = client.execute_read(
        f"""
        MATCH (current:Investigation {{id: $investigation_id}})
        MATCH (other:Investigation)
        WHERE other.id <> current.id
        OPTIONAL MATCH (current)-[*1..{TRAVERSAL_MAX_HOPS}]-(shared)<-[*1..{TRAVERSAL_MAX_HOPS}]-(other)
        WHERE shared IS NOT NULL AND NOT shared:Investigation
        WITH other,
             collect(DISTINCT
               CASE head(labels(shared))
                 WHEN 'Service' THEN 'Service:' + shared.name
                 WHEN 'Commit' THEN 'Commit:' + shared.sha
                 WHEN 'Deployment' THEN 'Deployment:' + shared.id
                 WHEN 'AlertEvent' THEN 'AlertEvent:' + shared.id
                 WHEN 'KnownIssue' THEN 'KnownIssue:' + shared.id
                 WHEN 'Build' THEN 'Build:' + shared.id
                 WHEN 'PagerDutyIncident' THEN 'PagerDutyIncident:' + shared.id
                 WHEN 'Runbook' THEN 'Runbook:' + shared.id
                 WHEN 'Pod' THEN 'Pod:' + shared.id
                 WHEN 'Container' THEN 'Container:' + shared.id
                 WHEN 'Node' THEN 'Node:' + shared.id
                 ELSE null
               END
             ) AS entity_keys,
             collect(DISTINCT
               CASE
                 WHEN 'Pod' IN labels(shared) AND shared.reason = 'CrashLoopBackOff' THEN 'K8sSignal:CrashLoopBackOff'
                 WHEN 'Pod' IN labels(shared) AND shared.reason = 'OOMKilled' THEN 'K8sSignal:OOMKilled'
                 WHEN 'Pod' IN labels(shared) AND shared.reason = 'FailedScheduling' THEN 'K8sSignal:FailedScheduling'
                 WHEN 'Pod' IN labels(shared) AND shared.reason IN ['ErrImagePull', 'ImagePullBackOff', 'ImagePullFailure'] THEN 'K8sSignal:ImagePullFailure'
                 WHEN 'Container' IN labels(shared) AND shared.reason IN ['ErrImagePull', 'ImagePullBackOff', 'ImagePullFailure'] THEN 'K8sSignal:ImagePullFailure'
                 WHEN 'Pod' IN labels(shared) AND coalesce(shared.restart_count, 0) >= {HIGH_RESTART_COUNT_THRESHOLD} THEN 'K8sSignal:HighRestartCount'
                 WHEN 'Pod' IN labels(shared) AND coalesce(shared.restart_count, 0) > 0 THEN 'K8sSignal:ContainerRestart'
                 WHEN 'Container' IN labels(shared) AND shared.reason = 'CrashLoopBackOff' THEN 'K8sSignal:CrashLoopBackOff'
                 WHEN 'Container' IN labels(shared) AND shared.reason = 'OOMKilled' THEN 'K8sSignal:OOMKilled'
                 WHEN 'Container' IN labels(shared) AND (
                   shared.reason IN ['Error', 'Failed', 'CrashLoopBackOff'] OR
                   toLower(coalesce(shared.status, '')) = 'terminated'
                 ) THEN 'K8sSignal:ContainerFailure'
                 WHEN 'Node' IN labels(shared) AND shared.status = 'MemoryPressure' THEN 'K8sSignal:NodeMemoryPressure'
                 WHEN 'Node' IN labels(shared) AND shared.status = 'DiskPressure' THEN 'K8sSignal:NodeDiskPressure'
                 WHEN 'Node' IN labels(shared) AND (
                   shared.status IN ['MemoryPressure', 'DiskPressure', 'PIDPressure', 'NotReady', 'Pressure'] OR
                   toLower(coalesce(shared.status, '')) CONTAINS 'pressure'
                 ) THEN 'K8sSignal:NodePressure'
                 ELSE null
               END
             ) AS signal_keys
        WITH other,
             [k IN entity_keys WHERE k IS NOT NULL] + [k IN signal_keys WHERE k IS NOT NULL] AS shared_keys
        RETURN other.id AS investigation_id,
               other.ticket_key AS ticket_key,
               other.created_at AS created_at,
               [k IN shared_keys WHERE k IS NOT NULL] AS shared_keys
        """,
        {"investigation_id": investigation_id},
    )

    scored: list[SimilarInvestigation] = []
    store = _get_investigation_store()

    for row in rows:
        other_id = str(row.get("investigation_id") or "").strip()
        if not other_id:
            continue
        shared_keys = [str(k) for k in (row.get("shared_keys") or []) if k]
        other_paths = _file_paths_for_investigation(other_id)
        root_overlap = bool(current_paths and other_paths and current_paths.intersection(other_paths))
        similarity, factors = _score_shared_keys(shared_keys, root_cause_overlap=root_overlap)
        kubernetes_score = _compute_kubernetes_similarity_score(factors, shared_keys)
        if similarity <= 0 and kubernetes_score <= 0:
            continue
        if similarity <= 0 and kubernetes_score > 0:
            similarity = kubernetes_score

        match_explanation = _build_match_explanation(factors, shared_keys)

        store_record = None
        try:
            store_record = store.get_record(other_id)
        except Exception:
            store_record = None

        item = SimilarInvestigation(
            investigation_id=other_id,
            similarity_score=similarity,
            kubernetes_similarity_score=kubernetes_score,
            matched_factors=factors,
            match_explanation=match_explanation,
            created_at=row.get("created_at"),
        )
        scored.append(
            _enrich_similar_investigation(
                item,
                shared_keys=shared_keys,
                store_record=store_record,
            )
        )

    feedback_map = get_feedback_by_investigation_ids(
        client,
        [s.investigation_id for s in scored],
    )
    scored = [
        item.model_copy(
            update={
                "historical_feedback": _feedback_to_historical(
                    feedback_map.get(item.investigation_id, [])
                ),
            }
        )
        for item in scored
    ]

    scored.sort(
        key=lambda s: (
            -s.similarity_score,
            -s.kubernetes_similarity_score,
            s.created_at or "",
            s.investigation_id,
        )
    )
    return scored[:max_rows]
