"""Registry of tools available to debug agents. Wraps existing RCA platform capabilities."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_TOOLS: dict[str, Callable[..., Any]] = {}


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a tool by name."""

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _TOOLS[name] = fn
        return fn

    return _decorator


def get_registry() -> dict[str, Callable[..., Any]]:
    """Return the tool registry (read-only view)."""
    return dict(_TOOLS)


def invoke(name: str, *args: Any, **kwargs: Any) -> Any:
    """Invoke a registered tool by name."""
    fn = _TOOLS.get(name)
    if fn is None:
        raise KeyError(f"Unknown tool: {name}")
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Tool implementations (wrappers over existing modules)
# ---------------------------------------------------------------------------


@register("run_deterministic_rca")
def run_deterministic_rca(anomaly_id: str, *, run_id: Optional[str] = None, override: bool = False) -> Optional[dict[str, Any]]:
    """Run deterministic RCA for an anomaly. Returns run summary or None if blocked."""
    from api.services.rca_service import run_rca

    logger.info("tool.run_deterministic_rca anomaly_id=%s run_id=%s", anomaly_id, run_id)
    result = run_rca(
        anomaly_id,
        trigger_type="manual",
        run_id=run_id,
        override=override,
    )
    if result:
        logger.info("tool.run_deterministic_rca success run_id=%s count=%s", result.get("run_id"), result.get("attribution_count"))
    else:
        logger.warning("tool.run_deterministic_rca blocked anomaly_id=%s", anomaly_id)
    return result


@register("get_rca_results")
def get_rca_results(anomaly_id: str) -> list[dict[str, Any]]:
    """Get current RCA_ATTRIBUTED candidates for an anomaly."""
    from api.services.rca_service import get_rca_results as _get

    logger.info("tool.get_rca_results anomaly_id=%s", anomaly_id)
    rows = _get(anomaly_id)
    logger.info("tool.get_rca_results count=%s", len(rows))
    return rows


@register("get_graphrag_explanation")
def get_graphrag_explanation(anomaly_id: str, *, run_id: Optional[str] = None) -> dict[str, Any]:
    """Get GraphRAG explanation for latest deterministic RCA run."""
    from api.services.rca_service import get_rca_explanation

    logger.info("tool.get_graphrag_explanation anomaly_id=%s run_id=%s", anomaly_id, run_id)
    out = get_rca_explanation(anomaly_id, run_id=run_id)
    logger.info("tool.get_graphrag_explanation done primary=%s", out.get("primary_candidate", {}).get("path"))
    return out


def _get_evidence_store():
    """Create evidence store from env (same pattern as rca_service)."""
    from artifacts.evidence_store import LocalFileEvidenceStore

    base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    return LocalFileEvidenceStore(Path(base) / "evidence_bundles")


@register("get_evidence_bundle")
def get_evidence_bundle(bundle_id: str) -> Optional[dict[str, Any]]:
    """Retrieve evidence bundle by ID from evidence store."""
    logger.info("tool.get_evidence_bundle bundle_id=%s", bundle_id[:24] if len(bundle_id) > 24 else bundle_id)
    store = _get_evidence_store()
    bundle = store.get_bundle(bundle_id)
    if bundle:
        logger.info("tool.get_evidence_bundle found")
    else:
        logger.warning("tool.get_evidence_bundle not_found bundle_id=%s", bundle_id[:24] if len(bundle_id) > 24 else bundle_id)
    return bundle


@register("get_related_commits")
def get_related_commits(file_id: str) -> list[dict[str, Any]]:
    """Get commits that touched a file (File <- TOUCHED <- Commit)."""
    from graph.neo4j_client import Neo4jClient

    logger.info("tool.get_related_commits file_id=%s", file_id[:16] if len(file_id) > 16 else file_id)
    client = Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        q = """
        MATCH (f:File {file_id: $file_id})<-[:TOUCHED]-(c:Commit)
        RETURN c.sha AS sha, c.repo_ref AS repo_ref, c.timestamp AS timestamp
        ORDER BY c.timestamp DESC
        LIMIT 50
        """
        rows = client.execute_read(q, {"file_id": file_id})
        logger.info("tool.get_related_commits count=%s", len(rows))
        return [dict(r) for r in rows]
    finally:
        client.close()


@register("get_deployment_context")
def get_deployment_context(anomaly_id: str) -> dict[str, Any]:
    """Get deployment context for an anomaly: service_ref, anomaly timestamp, recent deployments."""
    from graph.neo4j_client import Neo4jClient

    logger.info("tool.get_deployment_context anomaly_id=%s", anomaly_id)
    client = Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        q_meta = """
        MATCH (a:Anomaly {id: $anomaly_id})
        RETURN a.service_ref AS service_ref, a.timestamp AS anomaly_ts
        """
        meta = client.execute_read(q_meta, {"anomaly_id": anomaly_id})
        service_ref = meta[0].get("service_ref") if meta else None
        anomaly_ts = meta[0].get("anomaly_ts") if meta else None

        out: dict[str, Any] = {"service_ref": service_ref, "anomaly_ts": anomaly_ts, "deployments": []}
        if service_ref:
            q_dep = """
            MATCH (d:Deployment)
            WHERE d.service_ref = $service_ref AND d.timestamp IS NOT NULL
            RETURN d.id AS id, d.timestamp AS timestamp
            ORDER BY d.timestamp DESC
            LIMIT 10
            """
            rows = client.execute_read(q_dep, {"service_ref": service_ref})
            out["deployments"] = [dict(r) for r in rows]
        logger.info("tool.get_deployment_context deployments=%s", len(out.get("deployments", [])))
        return out
    finally:
        client.close()


@register("get_similar_incidents")
def get_similar_incidents(anomaly_id: str, *, file_ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Get prior anomalies that attributed the same file(s). Excludes current anomaly."""
    from graph.neo4j_client import Neo4jClient

    logger.info("tool.get_similar_incidents anomaly_id=%s file_ids=%s", anomaly_id, len(file_ids) if file_ids else 0)
    client = Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        if not file_ids:
            q_files = """
            MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(f:File)
            WHERE r.status IN ['candidate', 'accepted']
            RETURN collect(DISTINCT f.file_id) AS ids
            """
            res = client.execute_read(q_files, {"anomaly_id": anomaly_id})
            file_ids = res[0].get("ids", []) if res else []
        if not file_ids:
            logger.info("tool.get_similar_incidents no_file_ids")
            return []
        q = """
        MATCH (a2:Anomaly)-[r:RCA_ATTRIBUTED]->(f:File)
        WHERE f.file_id IN $file_ids
          AND r.status IN ['accepted', 'candidate']
          AND a2.id <> $anomaly_id
        RETURN a2.id AS anomaly_id, f.file_id AS file_id, f.path AS path
        """
        rows = client.execute_read(q, {"file_ids": file_ids, "anomaly_id": anomaly_id})
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            aid = r.get("anomaly_id")
            if aid and aid not in seen:
                seen.add(aid)
                out.append({"anomaly_id": aid, "file_id": r.get("file_id"), "path": r.get("path")})
        logger.info("tool.get_similar_incidents count=%s", len(out))
        return out
    finally:
        client.close()


@register("get_feedback_history")
def get_feedback_history(file_id: str) -> list[dict[str, Any]]:
    """Get feedback history for RCA_ATTRIBUTED edges involving a file (feedback_at, feedback_actor_id, etc.)."""
    from graph.neo4j_client import Neo4jClient

    logger.info("tool.get_feedback_history file_id=%s", file_id[:16] if len(file_id) > 16 else file_id)
    client = Neo4jClient.from_env()
    if not getattr(client, "_driver", None):
        client.connect()
    try:
        q = """
        MATCH (a:Anomaly)-[r:RCA_ATTRIBUTED]->(f:File {file_id: $file_id})
        WHERE r.feedback_at IS NOT NULL
        RETURN a.id AS anomaly_id, r.run_id AS run_id,
               r.feedback_at AS feedback_at, r.feedback_actor_id AS feedback_actor_id,
               r.feedback_reason AS feedback_reason, r.status AS status
        ORDER BY r.feedback_at DESC
        LIMIT 20
        """
        rows = client.execute_read(q, {"file_id": file_id})
        logger.info("tool.get_feedback_history count=%s", len(rows))
        return [dict(r) for r in rows]
    finally:
        client.close()
