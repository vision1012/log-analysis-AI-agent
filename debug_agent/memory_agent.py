"""Memory agent: deterministic historical intelligence from Neo4j."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient

from debug_agent.shared_types import DebugContext, MemoryPackage, StepKind, StepResult
from debug_agent.tool_registry import invoke

logger = logging.getLogger(__name__)


def _file_ids_from_rca_output(rca_output: dict[str, Any]) -> list[str]:
    raw = rca_output.get("candidates") if isinstance(rca_output, dict) else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for c in raw:
        if isinstance(c, dict):
            fid = str(c.get("file_id") or "")
            if fid and fid not in out:
                out.append(fid)
    return out


def _recurrence_score(similar_count: int, prior_count: int) -> float:
    # Compact deterministic score in [0,1].
    raw = (0.6 * min(similar_count, 10) / 10.0) + (0.4 * min(prior_count, 10) / 10.0)
    return round(max(0.0, min(1.0, raw)), 2)


def run(
    context: DebugContext,
    *,
    params: Optional[dict[str, Any]] = None,
) -> StepResult:
    """
    Fetch deterministic memory package:
    - similar incidents
    - recurrence patterns
    - prior RCA for same file/service
    - feedback history
    """
    payload = params or {}
    anomaly_id = str(payload.get("anomaly_id") or context.anomaly_id or "")
    rca_output = payload.get("rca_result") if isinstance(payload.get("rca_result"), dict) else {}

    if not anomaly_id:
        return StepResult(
            step_kind=StepKind.MEMORY,
            success=False,
            output={},
            error="missing anomaly_id",
        )

    logger.info("debug_agent.memory_agent.start anomaly_id=%s", anomaly_id)

    try:
        file_ids = _file_ids_from_rca_output(rca_output)
        similar_incidents = invoke("get_similar_incidents", anomaly_id, file_ids=file_ids or None)

        feedback_history: list[dict[str, Any]] = []
        for fid in file_ids[:3]:
            rows = invoke("get_feedback_history", fid)
            if isinstance(rows, list):
                feedback_history.extend([r for r in rows if isinstance(r, dict)])

        # Additional graph query: prior root causes for same service/file.
        client = Neo4jClient.from_env()
        if not getattr(client, "_driver", None):
            client.connect()
        try:
            q = """
            MATCH (a:Anomaly {id: $anomaly_id})
            OPTIONAL MATCH (a2:Anomaly)-[r:RCA_ATTRIBUTED]->(f:File)
            WHERE a2.id <> $anomaly_id
              AND r.status IN ['accepted', 'candidate']
              AND ($service_ref IS NULL OR a2.service_ref = $service_ref)
              AND ($file_ids_len = 0 OR f.file_id IN $file_ids)
            RETURN a.service_ref AS service_ref,
                   f.file_id AS file_id,
                   f.path AS path,
                   count(DISTINCT a2) AS prior_count
            ORDER BY prior_count DESC
            LIMIT 20
            """
            service_rows = client.execute_read(
                "MATCH (a:Anomaly {id: $anomaly_id}) RETURN a.service_ref AS service_ref",
                {"anomaly_id": anomaly_id},
            )
            service_ref = service_rows[0].get("service_ref") if service_rows else None
            prior_root_causes = client.execute_read(
                q,
                {
                    "anomaly_id": anomaly_id,
                    "service_ref": service_ref,
                    "file_ids": file_ids,
                    "file_ids_len": len(file_ids),
                },
            )
        finally:
            client.close()

        similar_count = len(similar_incidents) if isinstance(similar_incidents, list) else 0
        prior_count_total = sum(int(x.get("prior_count") or 0) for x in prior_root_causes if isinstance(x, dict))
        recurrence = _recurrence_score(similar_count, prior_count_total)

        if similar_count == 0 and prior_count_total == 0:
            pattern_summary = "No strong historical recurrence found for this anomaly/service."
        else:
            pattern_summary = (
                f"Found {similar_count} similar incidents and {prior_count_total} prior attributions "
                f"across matching files/service."
            )

        package = MemoryPackage(
            anomaly_id=anomaly_id,
            similar_incidents=similar_incidents if isinstance(similar_incidents, list) else [],
            recurrence_score=recurrence,
            historical_patterns_summary=pattern_summary,
            prior_root_causes=[dict(x) for x in prior_root_causes if isinstance(x, dict)],
            # compatibility alias
            prior_attributions=[dict(x) for x in prior_root_causes if isinstance(x, dict)],
            metadata={
                "service_ref": service_ref if "service_ref" in locals() else None,
                "file_ids": file_ids,
                "feedback_history": feedback_history[:50],
                "history_status": "complete",
            },
        )

        logger.info(
            "debug_agent.memory_agent.done anomaly_id=%s similar=%s prior_total=%s recurrence=%s",
            anomaly_id,
            similar_count,
            prior_count_total,
            recurrence,
        )
        return StepResult(
            step_kind=StepKind.MEMORY,
            success=True,
            output=asdict(package),
            error=None,
        )
    except Exception as exc:
        logger.exception("debug_agent.memory_agent.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        fallback = MemoryPackage(
            anomaly_id=anomaly_id,
            similar_incidents=[],
            recurrence_score=0.0,
            historical_patterns_summary="Historical memory unavailable; fallback used.",
            prior_root_causes=[],
            prior_attributions=[],
            metadata={"history_status": "failed"},
        )
        return StepResult(
            step_kind=StepKind.MEMORY,
            success=False,
            output=asdict(fallback),
            error=f"memory_agent failed: {exc}",
        )
