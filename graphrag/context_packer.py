"""Pack graph-derived RCA explanation context for the LLM layer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from artifacts.evidence_store import EvidenceStore
from graph.investigation_retriever import InvestigationGraphRetriever
from graph.neo4j_client import Neo4jClient
from rca_engine.ranking_model import DEFAULT_WEIGHTS
from rca_engine.signal_computation import MAX_RECURRENCE_CAP

SCHEMA_VERSION = "1.0.0"
logger = logging.getLogger(__name__)


def _truncate_text(value: Any, max_len: int = 220) -> str:
    s = str(value or "")
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _to_float(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int = 0) -> int:
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _ensure_connected(client: Neo4jClient) -> None:
    if not getattr(client, "_driver", None):
        client.connect()


def _fetch_anomaly_metadata(client: Neo4jClient, anomaly_id: str) -> dict[str, Any]:
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})
    RETURN a.id AS anomaly_id,
           a.trace_ref AS trace_ref,
           a.service_ref AS service_ref
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    if not rows:
        return {"anomaly_id": anomaly_id, "trace_ref": "", "service_ref": ""}
    r = rows[0]
    return {
        "anomaly_id": r.get("anomaly_id") or anomaly_id,
        "trace_ref": r.get("trace_ref") or "",
        "service_ref": r.get("service_ref") or "",
    }


def _select_run_id(client: Neo4jClient, anomaly_id: str, run_id: Optional[str]) -> str:
    if run_id:
        return run_id
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
    WHERE r.status IN ['candidate', 'accepted']
    RETURN r.run_id AS run_id, coalesce(r.created_at, '') AS ts
    ORDER BY ts DESC
    LIMIT 1
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return (rows[0].get("run_id") if rows else "") or ""


def _fetch_candidates_for_run(
    client: Neo4jClient,
    anomaly_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    # Locked architecture: RCA_ATTRIBUTED -> File only.
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
    WHERE r.status IN ['candidate', 'accepted'] AND r.run_id = $run_id
    RETURN r.run_id AS run_id,
           r.status AS status,
           r.confidence AS confidence,
           r.evidence_ref AS evidence_ref,
           f.file_id AS file_id,
           f.path AS path
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id, "run_id": run_id})
    return [dict(r) for r in rows]


def _get_bundle_cached(
    evidence_store: EvidenceStore,
    evidence_ref: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not evidence_ref:
        return {}
    if evidence_ref in cache:
        return cache[evidence_ref]
    b = evidence_store.get_bundle(evidence_ref) or {}
    cache[evidence_ref] = b
    return b


def _signal_summary_from_bundle(bundle: dict[str, Any], max_signal_entries: int) -> list[dict[str, float | str]]:
    scores = bundle.get("signal_scores") or {}
    weights = bundle.get("weights_used") or DEFAULT_WEIGHTS
    if not isinstance(scores, dict):
        return []
    items = sorted(
        (
            (str(k), _to_float(v), _to_float(weights.get(k, 0.0)))
            for k, v in scores.items()
        ),
        key=lambda x: (-x[1], x[0]),
    )[:max_signal_entries]
    return [{"name": n, "score": s, "weight_used": w} for n, s, w in items]


def _candidate_sort_key(c: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -_to_float(c.get("capped_score"), _to_float(c.get("confidence"))),
        _to_int(c.get("frame_order"), 10_000),
        -_to_float(c.get("last_touch_recency"), 0.0),
        -_to_float(c.get("historical_recurrence"), 0.0),
        str(c.get("path") or ""),
    )


def _compact_record(record: Any, *, text_limit: int = 200) -> dict[str, Any]:
    data = record.model_dump() if hasattr(record, "model_dump") else dict(record)
    for key, value in list(data.items()):
        if isinstance(value, str) and len(value) > text_limit:
            data[key] = _truncate_text(value, text_limit)
    return data


def _pack_investigation_retrieval_context(
    graph_client: Neo4jClient,
    *,
    investigation_id: str = "",
    service_name: str = "",
    ticket_key: str = "",
    alert_id: str = "",
    max_items: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch MCP investigation graph context via InvestigationGraphRetriever."""
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

    try:
        retriever = InvestigationGraphRetriever(graph_client)
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

        commits: list[Any] = []
        if service:
            commits = retriever.get_recent_commits_for_service(service, limit=max_items)

        runbooks: list[Any] = []
        if service:
            runbooks = retriever.get_runbooks_for_service(service, limit=max_items)

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
            "related_commits": [_compact_record(c) for c in commits[:max_items]],
            "related_deployments": [_compact_record(d) for d in deployments[:max_items]],
            "related_alerts": [_compact_record(a) for a in alerts[:max_items]],
            "related_incidents": [_compact_record(i) for i in incidents[:max_items]],
            "runbooks": [_compact_record(r) for r in runbooks[:max_items]],
            "known_issues": [_compact_record(k) for k in known_issues[:max_items]],
            "previous_investigations": [_compact_record(p) for p in previous[:max_items]],
        }
    except Exception as exc:
        logger.warning(
            "graphrag.context_packer.investigation_retrieval_failed investigation_id=%s service=%s err=%s",
            investigation_id,
            service_name,
            exc,
        )
        return empty


def pack_context(
    anomaly_id: str,
    *,
    graph_client: Neo4jClient,
    evidence_store: EvidenceStore,
    run_id: Optional[str] = None,
    investigation_id: Optional[str] = None,
    service_name: Optional[str] = None,
    ticket_key: Optional[str] = None,
    alert_id: Optional[str] = None,
    max_candidates: int = 3,
    max_signal_entries: int = 6,
    max_investigation_items: int = 5,
) -> dict[str, Any]:
    """
    Build explanation context from graph RCA candidates and evidence bundles.

    Guarantees:
    - deterministic ordering
    - compact payload
    - no duplicate evidence refs
    - candidate cap at top 3 by default
    - excludes raw logs/full code blobs
    """
    _ensure_connected(graph_client)
    meta = _fetch_anomaly_metadata(graph_client, anomaly_id)
    selected_run_id = _select_run_id(graph_client, anomaly_id, run_id)
    rows = _fetch_candidates_for_run(graph_client, anomaly_id, selected_run_id)

    bundle_cache: dict[str, dict[str, Any]] = {}
    by_file: dict[str, dict[str, Any]] = {}

    for r in rows:
        file_id = str(r.get("file_id") or "")
        if not file_id:
            continue
        ref = str(r.get("evidence_ref") or "")
        bundle = _get_bundle_cached(evidence_store, ref, bundle_cache)
        signal_scores = bundle.get("signal_scores") or {}

        confidence = _to_float(r.get("confidence"), 0.0)
        raw_score = _to_float(bundle.get("raw_score"), confidence)
        capped_score = _to_float(bundle.get("capped_score"), confidence)
        frame_order = bundle.get("frame_order")
        last_touch_recency = _to_float(signal_scores.get("last_touch_recency"), 0.0) if isinstance(signal_scores, dict) else 0.0
        historical_recurrence = _to_float(signal_scores.get("historical_recurrence"), 0.0) if isinstance(signal_scores, dict) else 0.0

        candidate = {
            "file_id": file_id,
            "path": _truncate_text(r.get("path") or bundle.get("path") or ""),
            "confidence": confidence,
            "raw_score": raw_score,
            "capped_score": capped_score,
            "evidence_ref": ref,
            "frame_order": frame_order,
            "last_touch_recency": last_touch_recency,
            "historical_recurrence": historical_recurrence,
            "signal_summary": _signal_summary_from_bundle(bundle, max_signal_entries),
            "score_breakdown": dict(bundle.get("score_breakdown") or {}),
            "confidence_assessment": dict(bundle.get("confidence_assessment") or {}),
            "commit_deployment_evidence": {
                "last_touch_commit_sha": str(bundle.get("last_touch_commit_sha") or ""),
                "deployment_id": str(bundle.get("deployment_id") or ""),
                "deployment_timing_valid": _to_float(
                    signal_scores.get("deployment_timing_valid"), 0.0
                ) > 0.0 if isinstance(signal_scores, dict) else False,
                "is_most_recent_deployment": _to_float(
                    signal_scores.get("deploy_recency_rank"), 0.0
                ) > 0.0 if isinstance(signal_scores, dict) else False,
            },
            "historical_recurrence_evidence": {
                "prior_count": _to_int(
                    bundle.get("prior_count"),
                    int(round(historical_recurrence * MAX_RECURRENCE_CAP)),
                ),
                "normalized_score": historical_recurrence,
                "service_scope": str(meta.get("service_ref") or ""),
            },
        }
        existing = by_file.get(file_id)
        if not existing or _candidate_sort_key(candidate) < _candidate_sort_key(existing):
            by_file[file_id] = candidate

    ordered_all = sorted(by_file.values(), key=_candidate_sort_key)
    ordered: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for c in ordered_all:
        ref = str(c.get("evidence_ref") or "")
        # Keep payload compact and avoid duplicate evidence entries.
        if ref and ref in seen_refs:
            continue
        if ref:
            seen_refs.add(ref)
        ordered.append(c)
        if len(ordered) >= max_candidates:
            break

    candidates: list[dict[str, Any]] = []
    for i, c in enumerate(ordered, start=1):
        candidates.append(
            {
                "rank": i,
                "file_id": c["file_id"],
                "path": c["path"],
                "confidence": c["confidence"],
                "raw_score": c["raw_score"],
                "capped_score": c["capped_score"],
                "evidence_ref": c["evidence_ref"],
                "signal_summary": c["signal_summary"],
                "score_breakdown": c["score_breakdown"],
                "confidence_assessment": c["confidence_assessment"],
                "commit_deployment_evidence": c["commit_deployment_evidence"],
                "historical_recurrence_evidence": c["historical_recurrence_evidence"],
            }
        )

    resolved_service = (service_name or meta.get("service_ref") or "").strip()
    investigation_context = _pack_investigation_retrieval_context(
        graph_client,
        investigation_id=(investigation_id or "").strip(),
        service_name=resolved_service,
        ticket_key=(ticket_key or "").strip(),
        alert_id=(alert_id or "").strip(),
        max_items=max_investigation_items,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "anomaly_id": meta.get("anomaly_id") or anomaly_id,
        "trace_ref": meta.get("trace_ref") or "",
        "run_id": selected_run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "investigation_context": investigation_context,
    }
