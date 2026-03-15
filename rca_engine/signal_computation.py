"""
Compute the 10 deterministic signals from graph/confidence_signals.md.

Uses graph queries for last-touch commit, deployment proximity, recurrence, spike correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient

from rca_engine.candidate_generator import Candidate

# Decay window for last_touch_recency (seconds)
DECAY_WINDOW_SEC = 7 * 24 * 3600  # 7 days
MAX_RECURRENCE_CAP = 5
VALID_RESOLUTIONS = ("exact", "probable")


@dataclass
class SignalScores:
    """All 10 signals for one candidate."""

    top_frame: float
    frame_depth: float
    last_touch_recency: float
    deploy_proximity: float
    deploy_recency_rank: float
    historical_recurrence: float
    trace_completeness: float
    path_exclusion: float
    deployment_timing_valid: float
    file_frame_count: float

    def to_dict(self) -> dict[str, float]:
        return {
            "top_frame": self.top_frame,
            "frame_depth": self.frame_depth,
            "last_touch_recency": self.last_touch_recency,
            "deploy_proximity": self.deploy_proximity,
            "deploy_recency_rank": self.deploy_recency_rank,
            "historical_recurrence": self.historical_recurrence,
            "trace_completeness": self.trace_completeness,
            "path_exclusion": self.path_exclusion,
            "deployment_timing_valid": self.deployment_timing_valid,
            "file_frame_count": self.file_frame_count,
        }


def _parse_ts(ts: Any) -> Optional[float]:
    """Parse timestamp to Unix seconds. Handles ISO 8601 and numeric."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts) if ts > 1e10 else ts  # assume seconds if small
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


@dataclass
class CandidateSignals:
    """Signals plus metadata for evidence bundle."""

    scores: SignalScores
    last_commit_sha: str
    deployment_id: Optional[str]


def compute_signals(
    client: Neo4jClient,
    anomaly_id: str,
    candidates: list[Candidate],
    *,
    max_depth: int = 20,
    excluded_deployment_ids: Optional[list[str]] = None,
) -> list[CandidateSignals]:
    """
    Compute 10 signals for each candidate.

    Fetches anomaly context and per-file data via graph queries.
    Returns CandidateSignals with scores and bundle metadata (last_commit_sha, deployment_id).
    """
    ctx = _fetch_anomaly_context(client, anomaly_id, max_depth)
    if not ctx:
        return (
            [
                CandidateSignals(scores=_zero_signals(), last_commit_sha="", deployment_id=None)
                for _ in candidates
            ],
            {},
        )

    file_data = _fetch_file_data(
        client,
        anomaly_id,
        [c.file_id for c in candidates],
        ctx,
        excluded_deployment_ids or [],
    )

    result: list[CandidateSignals] = []
    for c in candidates:
        fd = file_data.get(c.file_id, {})
        scores = _compute_one(c, ctx, fd)
        result.append(
            CandidateSignals(
                scores=scores,
                last_commit_sha=fd.get("last_commit_sha") or "",
                deployment_id=fd.get("deployment_id"),
            )
        )
    return result, ctx or {}


def _zero_signals() -> SignalScores:
    return SignalScores(
        top_frame=0.0,
        frame_depth=0.0,
        last_touch_recency=0.0,
        deploy_proximity=0.0,
        deploy_recency_rank=0.0,
        historical_recurrence=0.0,
        trace_completeness=0.0,
        path_exclusion=1.0,
        deployment_timing_valid=0.0,
        file_frame_count=0.0,
    )


def _fetch_anomaly_context(
    client: Neo4jClient, anomaly_id: str, max_depth: int
) -> Optional[dict[str, Any]]:
    """Fetch anomaly timestamp, service_ref, and frame stats in scope."""
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
    """Fetch last-touch commit, deployment, recurrence per file."""
    if not file_ids:
        return {}

    anomaly_ts = ctx.get("anomaly_ts")
    service_ref = ctx.get("service_ref")

    # Last-touch commit per file
    q_touch = """
    MATCH (f:File)
    WHERE f.file_id IN $file_ids
    OPTIONAL MATCH (f)<-[:TOUCHED]-(c:Commit)
    WHERE c.timestamp IS NOT NULL
      AND ($anomaly_ts IS NULL OR toString(c.timestamp) <= $anomaly_ts_str)
    WITH f, c
    ORDER BY f.file_id, c.timestamp DESC
    WITH f.file_id AS file_id, collect(c)[0] AS last_commit
    RETURN file_id,
           last_commit.sha AS last_commit_sha,
           last_commit.timestamp AS last_commit_ts,
           last_commit.repo_ref AS repo_ref
    """
    anomaly_ts_str = str(int(anomaly_ts)) if anomaly_ts else None
    touch_rows = client.execute_read(
        q_touch,
        {
            "file_ids": file_ids,
            "anomaly_ts": anomaly_ts,
            "anomaly_ts_str": anomaly_ts_str,
        },
    )

    # Frame count per file (frames in scope pointing to file)
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

    # Historical recurrence: prior RCA_ATTRIBUTED for same file + service_ref
    q_recur = """
    MATCH (a2:Anomaly)-[r:RCA_ATTRIBUTED]->(s:StackFrame)-[:IN_FILE]->(f:File)
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

    # Deployments: find deployment for last-touch commit, service_ref match
    # Most recent deployment before anomaly for service_ref
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
    excluded = excluded_deployment_ids or []
    deploy_ctx = client.execute_read(
        q_deploy,
        {
            "service_ref": service_ref or "",
            "anomaly_ts_str": anomaly_ts_str,
            "excluded": excluded,
        },
    )
    most_recent_dep_id = deploy_ctx[0]["most_recent_dep_id"] if deploy_ctx else None
    most_recent_dep_ts = _parse_ts(deploy_ctx[0]["most_recent_dep_ts"]) if deploy_ctx else None

    # Per-file: deployment that deployed last-touch commit
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
        }

    return out


def _compute_one(
    c: Candidate,
    ctx: dict[str, Any],
    fd: dict[str, Any],
) -> SignalScores:
    total = ctx.get("total_frames") or 1
    max_order = ctx.get("max_order") or 0
    resolved = ctx.get("resolved_count") or 0
    anomaly_ts = ctx.get("anomaly_ts")

    # 1. top_frame
    top_frame = 1.0 if c.representative_frame_order == 0 else 0.0

    # 2. frame_depth
    frame_depth = (
        1.0 - (c.representative_frame_order / max_order)
        if max_order > 0
        else 1.0
    )
    frame_depth = _clamp(frame_depth)

    # 3. last_touch_recency (commit must be before anomaly)
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

    # 7. trace_completeness
    trace_completeness = resolved / total if total > 0 else 0.0

    # 8. path_exclusion (candidates already filtered; always 1)
    path_exclusion = 1.0

    # 9. deployment_timing_valid
    deployment_timing_valid = (
        1.0
        if fd.get("deployment_ts") is not None
        and anomaly_ts is not None
        and fd.get("deployment_ts", 0) < anomaly_ts
        else 0.0
    )

    # 10. file_frame_count
    fc = fd.get("frame_count", 0)
    file_frame_count = _clamp(fc / total) if total > 0 else 0.0

    return SignalScores(
        top_frame=top_frame,
        frame_depth=frame_depth,
        last_touch_recency=last_touch_recency,
        deploy_proximity=deploy_proximity,
        deploy_recency_rank=deploy_recency_rank,
        historical_recurrence=historical_recurrence,
        trace_completeness=trace_completeness,
        path_exclusion=path_exclusion,
        deployment_timing_valid=deployment_timing_valid,
        file_frame_count=file_frame_count,
    )
