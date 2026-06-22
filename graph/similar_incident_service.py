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
}

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
    (service, deployment, alert, known issue, commit, build, PagerDuty incident, runbook)
    plus optional root-cause file-path overlap from persisted investigation records.
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
                 ELSE null
               END
             ) AS shared_keys
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
        if similarity <= 0:
            continue

        store_record = None
        try:
            store_record = store.get_record(other_id)
        except Exception:
            store_record = None

        item = SimilarInvestigation(
            investigation_id=other_id,
            similarity_score=similarity,
            matched_factors=factors,
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
            s.created_at or "",
            s.investigation_id,
        )
    )
    return scored[:max_rows]
