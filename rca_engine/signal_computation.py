"""
Compute deterministic signals for RCA scoring.

Uses Neo4j queries only. Returns {file_id: signal_scores}.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

from graph.neo4j_client import Neo4jClient

from rca_engine.candidate_generator import Candidate
from rca_engine.mcp_signal_config import (
    alert_correlation_points,
    deployment_proximity_points,
    historical_investigation_points,
    incident_severity_points,
    known_issue_match_points,
    mcp_rca_signals_enabled,
)
from rca_engine.mcp_context_signals import (
    MCP_CONTEXT_SIGNAL_NAMES,
    compute_mcp_context_signals_for_path,
    mcp_context_has_data,
)

# Decay window for recency signals (seconds)
DECAY_WINDOW_SEC = 7 * 24 * 3600  # 7 days
MAX_RECURRENCE_CAP = 5
VALID_RESOLUTIONS = ("exact", "probable", "resolved")

KEYWORD_ALIGNMENT_SIGNAL = "keyword_alignment"

KEYWORD_CATEGORIES: tuple[str, ...] = (
    "Authentication",
    "Database",
    "Deployment",
    "Infrastructure",
    "Performance",
    "Networking",
    "Application",
)

KEYWORD_CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "Authentication": (
        "auth",
        "token",
        "otp",
        "login",
        "password",
        "jwt",
        "oauth",
        "unauthorized",
        "forbidden",
        "invalid token",
    ),
    "Database": (
        "database",
        "sql",
        "deadlock",
        "postgres",
        "mysql",
        "redis",
        "mongodb",
        "connection pool",
        "query",
    ),
    "Deployment": ("deploy", "rollout", "release", "rollback", "canary"),
    "Infrastructure": ("pod", "oom", "kubernetes", "k8s", "restart", "crashloop", "node", "container"),
    "Performance": ("timeout", "latency", "slow", "throttle", "backpressure"),
    "Networking": ("connection refused", "503", "502", "504", "network", "dns", "socket", "unreachable"),
    "Application": ("error", "exception", "failed", "panic", "stacktrace", "traceback"),
}

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
    KEYWORD_ALIGNMENT_SIGNAL,
)

MCP_SIGNAL_NAMES = (
    "deployment_proximity_mcp",
    "alert_correlation",
    "incident_severity",
    "known_issue_match",
    "historical_investigation",
)


@dataclass
class KeywordSignal:
    """Structured keyword evidence extracted from logs and aligned to a candidate."""

    matched_keywords: list[str] = field(default_factory=list)
    keyword_score: float = 0.0
    keyword_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched_keywords": list(self.matched_keywords),
            "keyword_score": round(float(self.keyword_score), 4),
            "keyword_categories": list(self.keyword_categories),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "KeywordSignal":
        if not isinstance(data, dict):
            return cls()
        return cls(
            matched_keywords=[str(k) for k in (data.get("matched_keywords") or []) if k],
            keyword_score=float(data.get("keyword_score") or 0.0),
            keyword_categories=[str(c) for c in (data.get("keyword_categories") or []) if c],
        )


def _keyword_categories_for_text(text: str) -> set[str]:
    lowered = (text or "").lower()
    categories: set[str] = set()
    for category, patterns in KEYWORD_CATEGORY_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            categories.add(category)
    return categories


def _collect_keyword_hits(text: str) -> list[str]:
    lowered = (text or "").lower()
    hits: list[str] = []
    seen: set[str] = set()
    for patterns in KEYWORD_CATEGORY_PATTERNS.values():
        for pattern in patterns:
            if pattern in lowered and pattern not in seen:
                seen.add(pattern)
                hits.append(pattern)
    return hits


def compute_log_keyword_signal(
    log_content: str,
    *,
    extra_keywords: Optional[list[str]] = None,
) -> KeywordSignal:
    """Extract global keyword evidence from log text and optional ticket hints."""
    content = (log_content or "").strip()
    if not content and not extra_keywords:
        return KeywordSignal()

    base = extract_signals(content)
    matched: list[str] = []
    seen: set[str] = set()
    categories: set[str] = set()

    for kw in extra_keywords or []:
        token = str(kw or "").strip().lower()
        if token and token not in seen:
            seen.add(token)
            matched.append(token)
            categories.update(_keyword_categories_for_text(token))

    for line in (base.get("errors") or [])[:30]:
        for hit in _collect_keyword_hits(str(line)):
            if hit not in seen:
                seen.add(hit)
                matched.append(hit)
        categories.update(_keyword_categories_for_text(str(line)))

    for hit in _collect_keyword_hits(content):
        if hit not in seen:
            seen.add(hit)
            matched.append(hit)

    categories.update(_keyword_categories_for_text(content))

    for exc in base.get("exceptions") or []:
        token = str(exc).strip().lower()
        if token and token not in seen:
            seen.add(token)
            matched.append(token)
            categories.update(_keyword_categories_for_text(token))

    if int(base.get("timeout_count") or 0) > 0 and "timeout" not in seen:
        matched.append("timeout")
        categories.add("Performance")

    density = min(1.0, len(matched) / 6.0)
    category_bonus = min(0.35, 0.05 * len(categories))
    score = _clamp(density + category_bonus) if matched else 0.0

    return KeywordSignal(
        matched_keywords=matched[:40],
        keyword_score=score,
        keyword_categories=sorted(categories),
    )


def align_keyword_signal_for_path(
    path: str,
    log_signal: KeywordSignal,
    *,
    extra_keywords: Optional[list[str]] = None,
    log_files: Optional[list[str]] = None,
) -> tuple[float, KeywordSignal]:
    """Score how well a candidate path aligns with extracted keyword evidence."""
    if not log_signal.matched_keywords and not (extra_keywords or []) and not (log_files or []):
        return 0.0, KeywordSignal()

    path_l = (path or "").lower()
    basename = os.path.basename(path_l)
    all_keywords = list(
        dict.fromkeys([*(log_signal.matched_keywords or []), *(extra_keywords or [])])
    )

    path_keyword_hits = [kw for kw in all_keywords if kw.lower() in path_l]
    file_hits = [
        f for f in (log_files or [])
        if basename and (basename in str(f).lower() or str(f).lower() in path_l)
    ]

    alignment = 0.0
    if path_keyword_hits:
        alignment = min(
            1.0,
            0.45 + (len(path_keyword_hits) / max(1, min(4, len(all_keywords)))) * 0.55,
        )
    elif file_hits:
        alignment = 0.75

    path_categories = set()
    for category in log_signal.keyword_categories:
        if any(pattern in path_l for pattern in KEYWORD_CATEGORY_PATTERNS.get(category, ())):
            path_categories.add(category)

    keyword_score = _clamp(alignment * max(log_signal.keyword_score, 0.25)) if alignment > 0 else 0.0
    return keyword_score, KeywordSignal(
        matched_keywords=path_keyword_hits or log_signal.matched_keywords[:8],
        keyword_score=keyword_score,
        keyword_categories=sorted(path_categories or log_signal.keyword_categories),
    )


def extract_keyword_signals(log_content: str) -> dict[str, Any]:
    """
    Lightweight keyword-based signal extraction for log-only RCA fallback.

    Backward-compatible dict shape used by existing jira/log RCA fallback code.
    """
    signal = compute_log_keyword_signal(log_content)
    lines = [ln.strip() for ln in (log_content or "").splitlines() if ln.strip()]
    base = extract_signals(lines)
    return {
        "error_count": int(base.get("error_count") or 0),
        "timeout": int(base.get("timeout_count") or 0),
        "timeout_count": int(base.get("timeout_count") or 0),
        "invalid_token_count": int(base.get("invalid_token_count") or 0),
        "service": str(base.get("service") or ""),
        "patterns": list(base.get("patterns") or []),
        "exception_types": {},
        "matched_keywords": signal.matched_keywords,
        "keyword_score": signal.keyword_score,
        "keyword_categories": signal.keyword_categories,
    }


def extract_signals(log_lines: Union[str, list[str]]) -> dict[str, Any]:
    if isinstance(log_lines, str):
        lines_iter = [ln for ln in log_lines.splitlines() if ln.strip()]
    else:
        lines_iter = [ln for ln in log_lines if isinstance(ln, str) and ln.strip()]

    signals: dict[str, Any] = {
        "error_count": 0,
        "timeout_count": 0,
        "invalid_token_count": 0,
        "service": None,
        "patterns": [],
        "errors": [],
        "exceptions": [],
        "files": [],
        "latency": False,
    }

    seen_errors: set[str] = set()
    seen_exceptions: set[str] = set()
    seen_files: set[str] = set()
    for line in lines_iter:
        l = line.lower()

        if "error" in l:
            signals["error_count"] += 1
            if line not in seen_errors:
                signals["errors"].append(line)
                seen_errors.add(line)

        if "timeout" in l:
            signals["timeout_count"] += 1
            signals["latency"] = True

        if "invalid otp token" in l or "invalid token" in l:
            signals["invalid_token_count"] += 1

        if "auth-service" in l:
            signals["service"] = "auth-service"

        for token in line.replace(":", " ").split():
            t = token.strip("()[]{}<>,\"'")
            if t.endswith("Exception") or t.endswith("Error"):
                if t not in seen_exceptions:
                    signals["exceptions"].append(t)
                    seen_exceptions.add(t)
            if t.endswith(".py") and t not in seen_files:
                signals["files"].append(t)
                seen_files.add(t)

        # capture raw pattern
        if "error" in l or "timeout" in l:
            signals["patterns"].append(line)

    return signals


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


def _collect_ticket_keywords(unified_investigation_context: Any | None) -> list[str]:
    if unified_investigation_context is None:
        return []
    keywords: list[str] = []
    ticket = getattr(unified_investigation_context, "ticket_context", None)
    if ticket is not None:
        for label in getattr(ticket, "labels", []) or []:
            token = str(label or "").strip().lower()
            if token:
                keywords.append(token)
        for field_name in ("summary", "description"):
            text = str(getattr(ticket, field_name, "") or "")
            keywords.extend(_collect_keyword_hits(text))
    for doc in getattr(unified_investigation_context, "known_issue_documents", []) or []:
        for kw in getattr(doc, "error_keywords", []) or []:
            token = str(kw or "").strip().lower()
            if token:
                keywords.append(token)
    return list(dict.fromkeys(keywords))


def compute_signals(
    client: Neo4jClient,
    anomaly_id: str,
    candidate_files: list[Union[Candidate, dict[str, Any]]],
    *,
    max_depth: int = 20,
    excluded_deployment_ids: Optional[list[str]] = None,
    mcp_graph_context: Optional[dict[str, Any]] = None,
    unified_investigation_context: Any | None = None,
    investigation_id: str = "",
    log_content: str = "",
) -> dict[str, dict[str, float]]:
    """
    Compute signals for each candidate file. Neo4j queries only.

    Returns:
        {file_id: {signal_name: score}} for each candidate.
    """
    if not candidate_files:
        print("[RCA] Signals: {}")
        return {}

    # Normalize to (file_id, frame_order, path) per candidate
    file_ids: list[str] = []
    frame_order_by_file: dict[str, int] = {}
    path_by_file: dict[str, str] = {}
    for c in candidate_files:
        if isinstance(c, Candidate):
            fid = c.file_id
            order = c.representative_frame_order
            path = c.path
        else:
            fid = c.get("file_id", "")
            rep = c.get("representative_frame") or {}
            order = rep.get("frame_order", c.get("representative_frame_order", 999))
            path = str(c.get("path") or "")
        if fid:
            file_ids.append(fid)
            frame_order_by_file[fid] = order
            path_by_file[fid] = path

    ctx = _fetch_anomaly_context(client, anomaly_id, max_depth)
    if not ctx:
        empty_result = {fid: _zero_scores() for fid in file_ids}
        print(f"[RCA] Signals: {empty_result}")
        return empty_result

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

    ticket_keywords = _collect_ticket_keywords(unified_investigation_context)
    log_signal = compute_log_keyword_signal(log_content, extra_keywords=ticket_keywords)
    log_files = extract_signals(log_content).get("files") or [] if log_content.strip() else []
    keyword_context_available = bool(log_signal.matched_keywords or ticket_keywords or log_content.strip())

    for fid in file_ids:
        alignment, candidate_signal = align_keyword_signal_for_path(
            path_by_file.get(fid, ""),
            log_signal,
            extra_keywords=ticket_keywords,
            log_files=log_files,
        )
        result[fid][KEYWORD_ALIGNMENT_SIGNAL] = alignment
        result[fid]["keyword_signal"] = candidate_signal.to_dict()
        result[fid]["keyword_context_available"] = 1.0 if keyword_context_available else 0.0

    if mcp_rca_signals_enabled():
        mcp_signals, mcp_breakdowns = compute_mcp_signals(
            file_ids=file_ids,
            path_by_file=path_by_file,
            anomaly_ts=ctx.get("anomaly_ts"),
            service_ref=str(ctx.get("service_ref") or ""),
            mcp_graph_context=mcp_graph_context,
            unified_investigation_context=unified_investigation_context,
            graph_client=client,
            investigation_id=investigation_id,
        )
        for fid in file_ids:
            if fid in mcp_signals:
                result[fid].update(mcp_signals[fid])
            if fid in mcp_breakdowns:
                result[fid]["score_breakdown"] = mcp_breakdowns[fid]

    if mcp_context_has_data(unified_investigation_context):
        from rca_engine.mcp_signal_engine_v2 import (
            compute_mcp_signal_engine_v2,
            contributions_to_bundle_fields,
            contributions_to_signal_values,
        )
        from rca_engine.mcp_signal_v2_config import mcp_signal_v2_enabled

        for fid in file_ids:
            ctx_signals, ctx_refs = compute_mcp_context_signals_for_path(
                path_by_file.get(fid, ""),
                unified_investigation_context,
            )
            if any(v > 0 for v in ctx_signals.values()):
                result[fid].update(ctx_signals)
                result[fid]["mcp_artifact_refs"] = ctx_refs
                existing_breakdown = result[fid].get("score_breakdown")
                if not isinstance(existing_breakdown, dict):
                    existing_breakdown = {}
                for name, value in ctx_signals.items():
                    if value > 0:
                        existing_breakdown[f"mcp_ctx_{name}"] = round(float(value) * 3.0, 2)
                result[fid]["score_breakdown"] = existing_breakdown

            if mcp_signal_v2_enabled():
                v2 = compute_mcp_signal_engine_v2(
                    path_by_file.get(fid, ""),
                    unified_investigation_context,
                    mcp_graph_context=mcp_graph_context,
                    service_name=str(ctx.get("service_ref") or ""),
                    anomaly_timestamp=str(ctx.get("anomaly_ts") or "") or None,
                    error_keywords=ticket_keywords,
                )
                v2_values = contributions_to_signal_values(v2)
                if any(v > 0 for v in v2_values.values()):
                    result[fid].update(v2_values)
                    result[fid]["mcp_v2_contributions"] = contributions_to_bundle_fields(
                        v2, candidate_path=path_by_file.get(fid, "")
                    )
                    existing_breakdown = result[fid].get("score_breakdown")
                    if not isinstance(existing_breakdown, dict):
                        existing_breakdown = {}
                    for name, contrib in v2.items():
                        if contrib.value > 0:
                            existing_breakdown[f"mcp_v2_{name}"] = round(contrib.contribution * 100.0, 2)
                    result[fid]["score_breakdown"] = existing_breakdown

    print(f"[RCA] Signals: {result}")
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


def _minutes_before_anomaly(event_ts: Any, anomaly_ts: float | None) -> float | None:
    event = _parse_ts(event_ts)
    if event is None or anomaly_ts is None:
        return None
    if event > anomaly_ts:
        return None
    return (anomaly_ts - event) / 60.0


def _deployment_proximity_bucket(minutes: float | None) -> tuple[str, float, int]:
    if minutes is None:
        return ("none", 0.0, 0)
    if minutes <= 5:
        return ("0_5", 1.0, deployment_proximity_points("0_5"))
    if minutes <= 15:
        return ("5_15", 0.67, deployment_proximity_points("5_15"))
    if minutes <= 30:
        return ("15_30", 0.33, deployment_proximity_points("15_30"))
    return ("beyond_30", 0.0, 0)


def _collect_deployments(
    mcp_graph_context: dict[str, Any] | None,
    unified_context: Any | None,
) -> list[dict[str, Any]]:
    deployments: list[dict[str, Any]] = []
    if isinstance(mcp_graph_context, dict):
        for item in mcp_graph_context.get("related_deployments") or []:
            if isinstance(item, dict):
                deployments.append(item)
    if unified_context is not None:
        for dep in getattr(unified_context, "deployment_events", []) or []:
            deployments.append(dep.model_dump() if hasattr(dep, "model_dump") else dict(dep))
    return deployments


def _collect_alerts(
    mcp_graph_context: dict[str, Any] | None,
    unified_context: Any | None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if isinstance(mcp_graph_context, dict):
        for item in mcp_graph_context.get("related_alerts") or []:
            if isinstance(item, dict):
                alerts.append(item)
    if unified_context is not None:
        for alert in getattr(unified_context, "alert_events", []) or []:
            alerts.append(alert.model_dump() if hasattr(alert, "model_dump") else dict(alert))
    return alerts


def _collect_incidents(
    mcp_graph_context: dict[str, Any] | None,
    unified_context: Any | None,
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    if isinstance(mcp_graph_context, dict):
        for item in mcp_graph_context.get("related_incidents") or []:
            if isinstance(item, dict):
                incidents.append(item)
    if unified_context is not None:
        for incident in getattr(unified_context, "pagerduty_incidents", []) or []:
            incidents.append(incident.model_dump() if hasattr(incident, "model_dump") else dict(incident))
    return incidents


def _collect_known_issues(
    mcp_graph_context: dict[str, Any] | None,
    unified_context: Any | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if isinstance(mcp_graph_context, dict):
        for item in mcp_graph_context.get("known_issues") or []:
            if isinstance(item, dict):
                issues.append(item)
    if unified_context is not None:
        for doc in getattr(unified_context, "known_issue_documents", []) or []:
            issues.append(doc.model_dump() if hasattr(doc, "model_dump") else dict(doc))
    return issues


def _known_issue_matches_candidate(path: str, service_ref: str, issue: dict[str, Any]) -> bool:
    path_l = (path or "").lower()
    service_l = (service_ref or "").lower()
    affected = str(issue.get("affected_service") or "").lower()
    if affected and (affected in path_l or affected == service_l or affected in service_l):
        return True
    title = str(issue.get("title") or "").lower()
    if title and any(token in path_l for token in title.split() if len(token) > 3):
        return True
    for kw in issue.get("error_keywords") or []:
        token = str(kw or "").lower()
        if token and token in path_l:
            return True
    return False


def _fetch_historical_investigation_boost(
    graph_client: Neo4jClient | None,
    *,
    investigation_id: str,
    service_ref: str,
    path: str,
    mcp_graph_context: dict[str, Any] | None,
) -> tuple[float, int]:
    similarity = 0.0
    if isinstance(mcp_graph_context, dict):
        for item in mcp_graph_context.get("previous_investigations") or []:
            if not isinstance(item, dict):
                continue
            sim = float(item.get("similarity_score") or 0.0)
            if sim > similarity:
                similarity = sim

    if graph_client is not None and path:
        try:
            rows = graph_client.execute_read(
                """
                MATCH (a:Anomaly)-[r:RCA_ATTRIBUTED]->(f:File)
                WHERE f.path = $path
                  AND r.status IN ['accepted', 'candidate']
                  AND ($service_ref = '' OR a.service_ref = $service_ref)
                RETURN count(DISTINCT a) AS prior_count
                """,
                {"path": path, "service_ref": service_ref or ""},
            )
            if rows and int(rows[0].get("prior_count") or 0) > 0:
                similarity = max(similarity, 0.8)
        except Exception:
            pass

    points = historical_investigation_points(similarity) if similarity > 0 else 0
    return (min(1.0, similarity), points)


def compute_mcp_signals(
    *,
    file_ids: list[str],
    path_by_file: dict[str, str],
    anomaly_ts: float | None,
    service_ref: str,
    mcp_graph_context: dict[str, Any] | None = None,
    unified_investigation_context: Any | None = None,
    graph_client: Neo4jClient | None = None,
    investigation_id: str = "",
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """
    Compute MCP-derived signal values and point-based score breakdown per file.

    Returns:
        (signal_values, score_breakdown_points)
    """
    deployments = _collect_deployments(mcp_graph_context, unified_investigation_context)
    alerts = _collect_alerts(mcp_graph_context, unified_investigation_context)
    incidents = _collect_incidents(mcp_graph_context, unified_investigation_context)
    known_issues = _collect_known_issues(mcp_graph_context, unified_investigation_context)

    nearest_dep_minutes: float | None = None
    for dep in deployments:
        minutes = _minutes_before_anomaly(dep.get("deployed_at"), anomaly_ts)
        if minutes is None:
            continue
        if nearest_dep_minutes is None or minutes < nearest_dep_minutes:
            nearest_dep_minutes = minutes
    _, deploy_signal, deploy_points = _deployment_proximity_bucket(nearest_dep_minutes)

    top_alert = alerts[0] if alerts else {}
    alert_severity = str(top_alert.get("severity") or "")
    repeated_alert = len(alerts) > 1
    alert_signal = 1.0 if alert_severity in {"critical", "high", "sev1"} else (
        0.6 if alert_severity in {"warning", "medium", "warn", "sev2"} else 0.2
    )
    alert_points = alert_correlation_points(alert_severity, repeated=repeated_alert) if alerts else 0

    top_incident = incidents[0] if incidents else {}
    incident_urgency = str(top_incident.get("urgency") or "")
    incident_signal = 1.0 if incident_urgency in {"high", "critical"} else 0.4
    incident_points = incident_severity_points(incident_urgency) if incidents else 0

    signals_out: dict[str, dict[str, float]] = {}
    breakdown_out: dict[str, dict[str, float]] = {}

    for fid in file_ids:
        path = path_by_file.get(fid, "")
        known_match = any(_known_issue_matches_candidate(path, service_ref, issue) for issue in known_issues)
        known_signal = 1.0 if known_match else 0.0
        known_points = known_issue_match_points() if known_match else 0

        hist_signal, hist_points = _fetch_historical_investigation_boost(
            graph_client,
            investigation_id=investigation_id,
            service_ref=service_ref,
            path=path,
            mcp_graph_context=mcp_graph_context,
        )

        signals_out[fid] = {
            "deployment_proximity_mcp": deploy_signal,
            "alert_correlation": alert_signal,
            "incident_severity": incident_signal,
            "known_issue_match": known_signal,
            "historical_investigation": hist_signal,
        }
        breakdown: dict[str, float] = {}
        if deploy_points:
            breakdown["deployment_proximity"] = float(deploy_points)
        if alert_points:
            breakdown["alert_correlation"] = float(alert_points)
        if incident_points:
            breakdown["incident_severity"] = float(incident_points)
        if known_points:
            breakdown["known_issue_match"] = float(known_points)
        if hist_points:
            breakdown["historical_investigation"] = float(hist_points)
        breakdown_out[fid] = breakdown

    return signals_out, breakdown_out
