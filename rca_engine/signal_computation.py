"""
Compute deterministic signals for RCA scoring.

Uses Neo4j queries only. Returns {file_id: signal_scores}.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Union

from graph.neo4j_client import Neo4jClient

from rca_engine.candidate_generator import Candidate

# Decay window for recency signals (seconds)
DECAY_WINDOW_SEC = 7 * 24 * 3600  # 7 days
MAX_RECURRENCE_CAP = 5
VALID_RESOLUTIONS = ("exact", "probable", "resolved")

# Signal names
SIGNAL_NAMES = (
    "top_frame_presence",
    "frame_depth_penalty",
    "last_touch_recency",
    "deploy_proximity",
    "deploy_recency_rank",
    "historical_recurrence",
    "resolution_quality",
    "spike_correlation_strength",
    "trace_completeness",
    "file_touch_sparsity",
)


def _parse_ts(ts: Any) -> Optional[float]:
    """Parse timestamp to Unix seconds. Handles ISO 8601 and numeric."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts) if ts > 1e10 else ts
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _zero_scores() -> dict[str, float]:
    """All signals at 0 (or neutral)."""
    return {name: 0.0 for name in SIGNAL_NAMES}


def compute_signals(
    client: Neo4jClient,
    anomaly_id: str,
    candidate_files: list[Union[Candidate, dict[str, Any]]],
    *,
    max_depth: int = 20,
    excluded_deployment_ids: Optional[list[str]] = None,
) -> dict[str, dict[str, float]]:
    """
    Compute signals for each candidate file. Neo4j queries only.

    Returns:
        {file_id: {signal_name: score}} for each candidate.
    """
    if not candidate_files:
        return {}

    # Normalize to (file_id, frame_order) per candidate
    file_ids: list[str] = []
    frame_order_by_file: dict[str, int] = {}
    for c in candidate_files:
        if isinstance(c, Candidate):
            fid = c.file_id
            order = c.representative_frame_order
        else:
            fid = c.get("file_id", "")
            rep = c.get("representative_frame") or {}
            order = rep.get("frame_order", c.get("representative_frame_order", 999))
        if fid:
            file_ids.append(fid)
            frame_order_by_file[fid] = order

    ctx = _fetch_anomaly_context(client, anomaly_id, max_depth)
    if not ctx:
        return {fid: _zero_scores() for fid in file_ids}

    file_data = _fetch_file_data(
        client,
        anomaly_id,
        file_ids,
        ctx,
        excluded_deployment_ids or [],
    )

    result: dict[str, dict[str, float]] = {}
    for fid in file_ids:
        fd = file_data.get(fid, {})
        frame_order = frame_order_by_file.get(fid, 999)
        result[fid] = _compute_one(fid, frame_order, ctx, fd)
    return result


def fetch_anomaly_context(
    client: Neo4jClient, anomaly_id: str, max_depth: int = 20
) -> dict[str, Any]:
    """Fetch anomaly context (trace_ref, etc.) for bundle creation. Neo4j only."""
    ctx = _fetch_anomaly_context(client, anomaly_id, max_depth)
    return ctx or {}


def fetch_file_metadata(
    client: Neo4jClient,
    anomaly_id: str,
    file_ids: list[str],
    ctx: dict[str, Any],
    excluded_deployment_ids: Optional[list[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Fetch last_commit_sha, deployment_id per file for bundle creation. Neo4j only."""
    if not file_ids:
        return {}
    return _fetch_file_data(
        client, anomaly_id, file_ids, ctx, excluded_deployment_ids or []
    )


def _fetch_anomaly_context(
    client: Neo4jClient, anomaly_id: str, max_depth: int
) -> Optional[dict[str, Any]]:
    """Fetch anomaly timestamp, service_ref, frame stats via Neo4j."""
    q = """
    MATCH (a:Anomaly {id: $anomaly_id})
    OPTIONAL MATCH (a)-[r:HAS_FRAME]->(s:StackFrame)
    WHERE r.frame_order < $max_depth
    WITH a,
         count(s) AS total,
         collect(DISTINCT r.frame_order) AS orders,
         sum(CASE WHEN s.resolution IN $valid_resolutions THEN 1 ELSE 0 END) AS resolved
    RETURN a.timestamp AS anomaly_ts,
           a.service_ref AS service_ref,
           a.trace_ref AS trace_ref,
           total,
           resolved,
           orders
    """
    rows = client.execute_read(
        q,
        {
            "anomaly_id": anomaly_id,
            "max_depth": max_depth,
            "valid_resolutions": list(VALID_RESOLUTIONS),
        },
    )
    if not rows:
        return None
    r = rows[0]
    orders = [x for x in (r.get("orders") or []) if x is not None]
    max_order = max(orders) if orders else 0
    return {
        "anomaly_ts": _parse_ts(r.get("anomaly_ts")),
        "service_ref": r.get("service_ref"),
        "trace_ref": r.get("trace_ref"),
        "total_frames": r.get("total") or 0,
        "resolved_count": r.get("resolved") or 0,
        "max_order": max_order,
    }


def _fetch_file_data(
    client: Neo4jClient,
    anomaly_id: str,
    file_ids: list[str],
    ctx: dict[str, Any],
    excluded_deployment_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch last-touch commit, deployment, recurrence, touch count per file via Neo4j."""
    if not file_ids:
        return {}

    anomaly_ts = ctx.get("anomaly_ts")
    service_ref = ctx.get("service_ref")
    anomaly_ts_str = str(int(anomaly_ts)) if anomaly_ts else None
    excluded = excluded_deployment_ids or []

    # Last-touch commit per file
    q_touch = """
    MATCH (f:File)
    WHERE f.file_id IN $file_ids
    OPTIONAL MATCH (f)<-[:TOUCHED]-(c:Commit)
    WHERE c.timestamp IS NOT NULL
    WITH f, c
    ORDER BY f.file_id, c.timestamp DESC
    WITH f.file_id AS file_id, collect(c)[0] AS last_commit
    RETURN file_id,
           last_commit.sha AS last_commit_sha,
           last_commit.timestamp AS last_commit_ts,
           last_commit.repo_ref AS repo_ref
    """
    touch_rows = client.execute_read(
        q_touch,
        {"file_ids": file_ids},
    )

    # Touch count per file (for file_touch_sparsity)
    q_touch_count = """
    MATCH (f:File)<-[:TOUCHED]-(c:Commit)
    WHERE f.file_id IN $file_ids
    RETURN f.file_id AS file_id, count(c) AS touch_count
    """
    touch_count_rows = client.execute_read(q_touch_count, {"file_ids": file_ids})
    touch_counts = {r["file_id"]: r["touch_count"] for r in touch_count_rows}

    # Frame count per file
    q_frames = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:HAS_FRAME]->(s:StackFrame)-[:IN_FILE]->(f:File)
    WHERE r.frame_order < $max_depth AND f.file_id IN $file_ids
    RETURN f.file_id AS file_id, count(s) AS frame_count
    """
    frame_rows = client.execute_read(
        q_frames,
        {"anomaly_id": anomaly_id, "max_depth": ctx.get("max_order", 20) + 1, "file_ids": file_ids},
    )
    frame_counts = {r["file_id"]: r["frame_count"] for r in frame_rows}

    # Historical recurrence (locked: RCA_ATTRIBUTED -> File)
    q_recur = """
    MATCH (a2:Anomaly)-[r:RCA_ATTRIBUTED]->(f:File)
    WHERE f.file_id IN $file_ids
      AND r.status IN ['accepted', 'candidate']
      AND ($service_ref IS NULL OR a2.service_ref = $service_ref)
      AND a2.id <> $anomaly_id
    RETURN f.file_id AS file_id, count(DISTINCT a2) AS prior_count
    """
    recur_rows = client.execute_read(
        q_recur,
        {"file_ids": file_ids, "service_ref": service_ref, "anomaly_id": anomaly_id},
    )
    recur_counts = {r["file_id"]: r["prior_count"] for r in recur_rows}

    # Most recent deployment before anomaly
    q_deploy = """
    MATCH (d:Deployment)
    WHERE d.service_ref = $service_ref
      AND d.timestamp IS NOT NULL
      AND ($anomaly_ts_str IS NULL OR toString(d.timestamp) <= $anomaly_ts_str)
      AND NOT d.id IN $excluded
    WITH d
    ORDER BY d.timestamp DESC
    LIMIT 1
    RETURN d.id AS most_recent_dep_id, d.timestamp AS most_recent_dep_ts
    """
    deploy_ctx = client.execute_read(
        q_deploy,
        {
            "service_ref": service_ref or "",
            "anomaly_ts_str": anomaly_ts_str,
            "excluded": excluded,
        },
    )
    most_recent_dep_id = deploy_ctx[0]["most_recent_dep_id"] if deploy_ctx else None

    out: dict[str, dict[str, Any]] = {}
    for r in touch_rows:
        fid = r.get("file_id")
        if not fid:
            continue
        last_sha = r.get("last_commit_sha")
        last_ts = _parse_ts(r.get("last_commit_ts"))
        repo_ref = r.get("repo_ref")

        dep_id = None
        dep_ts = None
        is_most_recent = False
        if last_sha and repo_ref and service_ref:
            q_dep = """
            MATCH (d:Deployment)-[:DEPLOYED_COMMIT]->(c:Commit {sha: $sha, repo_ref: $repo_ref})
            WHERE d.service_ref = $service_ref
              AND d.timestamp IS NOT NULL
              AND ($anomaly_ts_str IS NULL OR toString(d.timestamp) <= $anomaly_ts_str)
              AND NOT d.id IN $excluded
            RETURN d.id AS dep_id, d.timestamp AS dep_ts
            ORDER BY d.timestamp DESC
            LIMIT 1
            """
            dep_rows = client.execute_read(
                q_dep,
                {
                    "sha": last_sha,
                    "repo_ref": repo_ref,
                    "service_ref": service_ref,
                    "anomaly_ts_str": anomaly_ts_str,
                    "excluded": excluded,
                },
            )
            if dep_rows:
                dep_id = dep_rows[0]["dep_id"]
                dep_ts = _parse_ts(dep_rows[0]["dep_ts"])
                is_most_recent = dep_id == most_recent_dep_id

        out[fid] = {
            "last_commit_sha": last_sha or "",
            "last_commit_ts": last_ts,
            "deployment_id": dep_id,
            "deployment_ts": dep_ts,
            "is_most_recent_deployment": is_most_recent,
            "frame_count": frame_counts.get(fid, 0),
            "prior_recurrence": recur_counts.get(fid, 0),
            "touch_count": touch_counts.get(fid, 0),
        }

    return out


def _compute_one(
    file_id: str,
    frame_order: int,
    ctx: dict[str, Any],
    fd: dict[str, Any],
) -> dict[str, float]:
    """Compute all 10 signals for one file."""
    total = ctx.get("total_frames") or 1
    max_order = ctx.get("max_order") or 0
    resolved = ctx.get("resolved_count") or 0
    anomaly_ts = ctx.get("anomaly_ts")

    # 1. top_frame_presence
    top_frame_presence = 1.0 if frame_order == 0 else 0.0

    # 2. frame_depth_penalty (higher = deeper = more penalty)
    frame_depth_penalty = (
        frame_order / max_order if max_order > 0 else 0.0
    )
    frame_depth_penalty = _clamp(frame_depth_penalty)

    # 3. last_touch_recency
    last_ts = fd.get("last_commit_ts")
    if last_ts is None or anomaly_ts is None or last_ts > anomaly_ts:
        last_touch_recency = 0.0
    else:
        delta = anomaly_ts - last_ts
        last_touch_recency = _clamp(1.0 - delta / DECAY_WINDOW_SEC)

    # 4. deploy_proximity
    dep_ts = fd.get("deployment_ts")
    if dep_ts is None or anomaly_ts is None:
        deploy_proximity = 0.0
    else:
        delta = anomaly_ts - dep_ts
        deploy_proximity = _clamp(1.0 - delta / DECAY_WINDOW_SEC)

    # 5. deploy_recency_rank
    deploy_recency_rank = 1.0 if fd.get("is_most_recent_deployment") else 0.0

    # 6. historical_recurrence
    prior = fd.get("prior_recurrence", 0)
    historical_recurrence = _clamp(prior / MAX_RECURRENCE_CAP)

    # 7. resolution_quality (fraction of resolved frames in trace)
    resolution_quality = resolved / total if total > 0 else 0.0

    # 8. spike_correlation_strength (deployment proximity as proxy; deployment near anomaly = spike)
    spike_correlation_strength = deploy_proximity  # same as deploy_proximity when data exists

    # 9. trace_completeness
    trace_completeness = resolved / total if total > 0 else 0.0

    # 10. file_touch_sparsity (sparse = few touches = higher; 1/(1+touch_count) normalized)
    touch_count = fd.get("touch_count", 0)
    file_touch_sparsity = _clamp(1.0 / (1.0 + touch_count)) if touch_count >= 0 else 0.0

    return {
        "top_frame_presence": top_frame_presence,
        "frame_depth_penalty": frame_depth_penalty,
        "last_touch_recency": last_touch_recency,
        "deploy_proximity": deploy_proximity,
        "deploy_recency_rank": deploy_recency_rank,
        "historical_recurrence": historical_recurrence,
        "resolution_quality": resolution_quality,
        "spike_correlation_strength": spike_correlation_strength,
        "trace_completeness": trace_completeness,
        "file_touch_sparsity": file_touch_sparsity,
    }
