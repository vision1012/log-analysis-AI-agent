"""Deterministic MCP Signal Engine v2 — additive RCA signals from unified investigation context."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from rca_engine.mcp_context_signals import (
    _basename,
    _commit_changed_files,
    _path_matches_changed_files,
    _pr_changed_files,
)
from rca_engine.mcp_signal_v2_config import (
    JIRA_LOG_V2_BOOST_CAP,
    JIRA_LOG_V2_BOOST_WEIGHTS,
    MCP_SIGNAL_V2_NAMES,
    churn_high_watermark,
    churn_windows_days,
    mcp_signal_v2_enabled,
    signal_v2_weights,
)

_ROLLBACK_STATUSES = frozenset({"rollback", "rolled_back", "reverted", "failed", "failure"})
_BUILD_FAILURE_STATUSES = frozenset({"failed", "failure", "error", "unstable", "aborted"})
_SEVERITY_RANK = {"critical": 1.0, "high": 0.85, "error": 0.8, "warning": 0.5, "warn": 0.5, "info": 0.25}


@dataclass
class SignalContribution:
    """One deterministic MCP v2 signal with scoring metadata."""

    name: str
    value: float
    weight: float
    contribution: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def finalize(self) -> SignalContribution:
        self.value = max(0.0, min(1.0, float(self.value)))
        self.contribution = round(self.value * self.weight, 6)
        return self


def _empty_contributions() -> dict[str, SignalContribution]:
    weights = signal_v2_weights()
    return {
        name: SignalContribution(name=name, value=0.0, weight=weights.get(name, 0.0)).finalize()
        for name in MCP_SIGNAL_V2_NAMES
    }


def _parse_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _anchor_time(
    *,
    anomaly_timestamp: str | None,
    unified_context: Any | None,
) -> datetime:
    for candidate in (anomaly_timestamp,):
        dt = _parse_iso(candidate)
        if dt:
            return dt
    for commit in _model_list(unified_context, "commits")[:5]:
        dt = _parse_iso(str(getattr(commit, "committed_at", "") or ""))
        if dt:
            return dt
    return datetime.now(timezone.utc)


def _model_list(obj: Any, attr: str) -> list[Any]:
    if obj is None:
        return []
    value = getattr(obj, attr, None)
    return list(value or [])


def _commits_touching_path(path: str, commits: list[Any]) -> list[Any]:
    out: list[Any] = []
    for commit in commits:
        changed = _commit_changed_files(commit)
        message = str(getattr(commit, "message", "") or getattr(commit, "title", "") or "")
        if _path_matches_changed_files(path, changed) or (
            _basename(path) and _basename(path) in message.lower()
        ):
            out.append(commit)
    return out


def _prs_touching_path(path: str, pull_requests: list[Any]) -> list[Any]:
    out: list[Any] = []
    for pr in pull_requests:
        changed = _pr_changed_files(pr)
        title = str(getattr(pr, "title", "") or "")
        if _path_matches_changed_files(path, changed) or (
            _basename(path) and _basename(path) in title.lower()
        ):
            out.append(pr)
    return out


def _compute_code_ownership(path: str, commits: list[Any], prs: list[Any]) -> SignalContribution:
    weight = signal_v2_weights()["code_ownership"]
    author_counts: dict[str, int] = {}
    for commit in commits:
        author = str(getattr(commit, "author", "") or "").strip().lower()
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
    for pr in prs:
        author = str(getattr(pr, "author", "") or "").strip().lower()
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
    if not author_counts:
        return SignalContribution("code_ownership", 0.0, weight, evidence={"owners": []}).finalize()
    total = sum(author_counts.values())
    owner, count = max(author_counts.items(), key=lambda item: item[1])
    ratio = count / max(total, 1)
    value = 1.0 if ratio >= 0.5 else (0.7 if ratio >= 0.35 else (0.4 if ratio >= 0.2 else 0.0))
    return SignalContribution(
        "code_ownership",
        value,
        weight,
        evidence={"primary_owner": owner, "touch_ratio": round(ratio, 4), "touch_count": count, "path": path},
    ).finalize()


def _compute_code_churn(path: str, commits: list[Any], anchor: datetime) -> SignalContribution:
    weight = signal_v2_weights()["code_churn"]
    windows = churn_windows_days()
    counts = {days: 0 for days in windows}
    for commit in commits:
        ts = _parse_iso(str(getattr(commit, "committed_at", "") or ""))
        if ts is None:
            continue
        age_days = (anchor - ts).total_seconds() / 86400.0
        if age_days < 0:
            continue
        for days in windows:
            if age_days <= days:
                counts[days] += 1
    weights_by_window = {7: 1.0, 30: 0.7, 90: 0.4}
    score = 0.0
    for days, count in counts.items():
        window_weight = weights_by_window.get(days, 0.3)
        score += window_weight * min(1.0, count / churn_high_watermark())
    value = min(1.0, score / max(len(windows), 1))
    return SignalContribution(
        "code_churn",
        value,
        weight,
        evidence={"churn_counts": counts, "anchor": anchor.isoformat(), "windows_days": list(windows)},
    ).finalize()


def _commit_shas_for_path(path: str, commits: list[Any]) -> set[str]:
    return {
        str(getattr(c, "sha", "") or getattr(c, "id", "") or "").strip()
        for c in _commits_touching_path(path, commits)
        if getattr(c, "sha", None) or getattr(c, "id", None)
    }


def _compute_deployment_proximity_v2(
    path: str,
    commits: list[Any],
    deployments: list[Any],
    anchor: datetime,
) -> SignalContribution:
    weight = signal_v2_weights()["deployment_proximity_v2"]
    shas = _commit_shas_for_path(path, commits)
    best_minutes: float | None = None
    best_id = ""
    for dep in deployments:
        dep_sha = str(getattr(dep, "commit_sha", "") or "").strip()
        if shas and dep_sha and dep_sha not in shas:
            continue
        dep_ts = _parse_iso(str(getattr(dep, "deployed_at", "") or ""))
        if dep_ts is None:
            continue
        delta_min = abs((anchor - dep_ts).total_seconds()) / 60.0
        if best_minutes is None or delta_min < best_minutes:
            best_minutes = delta_min
            best_id = str(getattr(dep, "deployment_id", "") or "")
    if best_minutes is None:
        return SignalContribution("deployment_proximity_v2", 0.0, weight).finalize()
    if best_minutes <= 5:
        value = 1.0
    elif best_minutes <= 15:
        value = 0.75
    elif best_minutes <= 30:
        value = 0.5
    elif best_minutes <= 120:
        value = 0.3
    else:
        value = 0.1
    return SignalContribution(
        "deployment_proximity_v2",
        value,
        weight,
        evidence={"deployment_id": best_id, "minutes_from_anchor": round(best_minutes, 2)},
    ).finalize()


def _compute_rollback(path: str, commits: list[Any], deployments: list[Any]) -> SignalContribution:
    weight = signal_v2_weights()["rollback"]
    shas = _commit_shas_for_path(path, commits)
    hits: list[dict[str, str]] = []
    for dep in deployments:
        status = str(getattr(dep, "status", "") or "").strip().lower()
        if status not in _ROLLBACK_STATUSES:
            continue
        dep_sha = str(getattr(dep, "commit_sha", "") or "").strip()
        if shas and dep_sha and dep_sha not in shas:
            continue
        hits.append(
            {
                "deployment_id": str(getattr(dep, "deployment_id", "") or ""),
                "status": status,
                "commit_sha": dep_sha[:12],
            }
        )
    value = 1.0 if hits else 0.0
    return SignalContribution("rollback", value, weight, evidence={"rollback_deployments": hits[:5]}).finalize()


def _compute_build_failure(path: str, commits: list[Any], builds: list[Any]) -> SignalContribution:
    weight = signal_v2_weights()["build_failure"]
    shas = _commit_shas_for_path(path, commits)
    failed: list[dict[str, str]] = []
    for build in builds:
        status = str(getattr(build, "status", "") or "").strip().lower()
        if status not in _BUILD_FAILURE_STATUSES:
            continue
        build_sha = str(getattr(build, "commit_sha", "") or "").strip()
        if shas and build_sha and build_sha not in shas:
            continue
        failed.append(
            {
                "build_id": str(getattr(build, "build_id", "") or ""),
                "status": status,
                "commit_sha": build_sha[:12],
            }
        )
    value = min(1.0, len(failed) / 2.0) if failed else 0.0
    return SignalContribution("build_failure", value, weight, evidence={"failed_builds": failed[:5]}).finalize()


def _compute_service_dependency(
    path: str,
    service_name: str,
    alerts: list[Any],
    incidents: list[Any],
    traces: list[Any],
    error_keywords: list[str],
) -> SignalContribution:
    weight = signal_v2_weights()["service_dependency"]
    svc = (service_name or "").strip().lower()
    related: list[dict[str, str]] = []
    keywords = [k.lower() for k in error_keywords if k]
    for alert in alerts:
        alert_svc = str(getattr(alert, "service", "") or "").strip().lower()
        text = f"{getattr(alert, 'title', '')} {getattr(alert, 'message', '')}".lower()
        if svc and alert_svc and alert_svc != svc:
            if not keywords or any(k in text for k in keywords):
                related.append({"type": "alert", "service": alert_svc, "id": str(getattr(alert, "alert_id", ""))})
    for incident in incidents:
        inc_svc = str(getattr(incident, "service_name", "") or "").strip().lower()
        title = str(getattr(incident, "title", "") or "").lower()
        if svc and inc_svc and inc_svc != svc:
            if not keywords or any(k in title for k in keywords):
                related.append(
                    {"type": "incident", "service": inc_svc, "id": str(getattr(incident, "incident_id", ""))}
                )
    for trace in traces:
        trace_svc = str(getattr(trace, "service", "") or "").strip().lower()
        if trace_svc and svc and trace_svc != svc and int(getattr(trace, "error_count", 0) or 0) > 0:
            related.append({"type": "trace", "service": trace_svc, "id": str(getattr(trace, "trace_id", ""))})
    value = min(1.0, len(related) / 3.0) if related else 0.0
    return SignalContribution(
        "service_dependency",
        value,
        weight,
        evidence={"related_failures": related[:8], "candidate_service": service_name},
    ).finalize()


def _compute_incident_recurrence(
    path: str,
    service_name: str,
    error_keywords: list[str],
    mcp_graph_context: dict[str, Any] | None,
) -> SignalContribution:
    weight = signal_v2_weights()["incident_recurrence"]
    prior = []
    if isinstance(mcp_graph_context, dict):
        prior = list(mcp_graph_context.get("previous_investigations") or [])
    path_l = (path or "").lower()
    svc = (service_name or "").strip().lower()
    keywords = [k.lower() for k in error_keywords if k]
    matches: list[dict[str, str]] = []
    for row in prior:
        if isinstance(row, dict):
            inv_id = str(row.get("investigation_id") or row.get("id") or "")
            ticket_key = str(row.get("ticket_key") or "")
            root = str(row.get("root_cause") or row.get("path") or "").lower()
            shared = str(row.get("shared_service") or row.get("service_name") or "").lower()
        else:
            inv_id = str(getattr(row, "investigation_id", "") or "")
            ticket_key = str(getattr(row, "ticket_key", "") or "")
            root = str(getattr(row, "root_cause", "") or "").lower()
            shared = str(getattr(row, "shared_service", "") or getattr(row, "service_name", "") or "").lower()
        hit = False
        if path_l and root and (path_l in root or _basename(path_l) in root):
            hit = True
        if svc and shared and svc == shared:
            hit = True
        if keywords and any(k in root for k in keywords):
            hit = True
        if hit and inv_id:
            matches.append({"investigation_id": inv_id, "ticket_key": ticket_key})
    value = min(1.0, len(matches) / 3.0) if matches else 0.0
    return SignalContribution(
        "incident_recurrence",
        value,
        weight,
        evidence={"prior_investigations": matches[:5]},
    ).finalize()


def _compute_alert_correlation_v2(
    path: str,
    service_name: str,
    alerts: list[Any],
    metrics: list[Any],
    traces: list[Any],
) -> SignalContribution:
    weight = signal_v2_weights()["alert_correlation_v2"]
    path_base = _basename(path)
    svc = (service_name or "").strip().lower()
    score = 0.0
    evidence_alerts: list[str] = []
    evidence_metrics: list[str] = []
    evidence_traces: list[str] = []
    for alert in alerts:
        text = f"{getattr(alert, 'title', '')} {getattr(alert, 'message', '')} {getattr(alert, 'service', '')}".lower()
        severity = str(getattr(alert, "severity", "") or "").lower()
        sev_score = _SEVERITY_RANK.get(severity, 0.4)
        aligned = (svc and svc in text) or (path_base and path_base in text)
        if aligned:
            score = max(score, sev_score)
            evidence_alerts.append(str(getattr(alert, "alert_id", "") or ""))
    for metric in metrics:
        metric_name = str(getattr(metric, "metric_name", "") or "").lower()
        metric_svc = str(getattr(metric, "service", "") or "").lower()
        if (svc and metric_svc == svc) or (path_base and path_base in metric_name):
            sev = str(getattr(metric, "severity", "") or "").lower()
            score = max(score, _SEVERITY_RANK.get(sev, 0.35))
            evidence_metrics.append(metric_name)
    for trace in traces:
        trace_svc = str(getattr(trace, "service", "") or "").lower()
        endpoint = str(getattr(trace, "endpoint", "") or "").lower()
        if (svc and trace_svc == svc) or (path_base and path_base in endpoint):
            if int(getattr(trace, "error_count", 0) or 0) > 0:
                score = max(score, 0.7)
                evidence_traces.append(str(getattr(trace, "trace_id", "") or ""))
    return SignalContribution(
        "alert_correlation_v2",
        min(1.0, score),
        weight,
        evidence={
            "alerts": [a for a in evidence_alerts if a][:5],
            "metrics": evidence_metrics[:5],
            "traces": evidence_traces[:5],
        },
    ).finalize()


def _compute_reviewer(path: str, prs: list[Any]) -> SignalContribution:
    weight = signal_v2_weights()["reviewer"]
    reviewers: dict[str, int] = {}
    matched_prs: list[dict[str, object]] = []
    for pr in prs:
        raw_reviewers = getattr(pr, "reviewers", None) or []
        pr_reviewers = [str(r).strip().lower() for r in raw_reviewers if str(r).strip()]
        author = str(getattr(pr, "author", "") or "").strip().lower()
        for reviewer in pr_reviewers:
            reviewers[reviewer] = reviewers.get(reviewer, 0) + 1
        if pr_reviewers:
            matched_prs.append({"number": getattr(pr, "number", 0), "reviewers": pr_reviewers, "author": author})
    if not reviewers:
        return SignalContribution("reviewer", 0.0, weight, evidence={"matched_prs": []}).finalize()
    top_reviewer, count = max(reviewers.items(), key=lambda item: item[1])
    value = min(1.0, 0.5 + (count / 4.0) * 0.5)
    return SignalContribution(
        "reviewer",
        value,
        weight,
        evidence={"top_reviewer": top_reviewer, "reviewer_touch_count": count, "matched_prs": matched_prs[:5]},
    ).finalize()


def _compute_author_expertise(path: str, commits: list[Any]) -> SignalContribution:
    weight = signal_v2_weights()["author_expertise"]
    touching = _commits_touching_path(path, commits)
    if not touching:
        return SignalContribution("author_expertise", 0.0, weight).finalize()
    counts: dict[str, int] = {}
    for commit in touching:
        author = str(getattr(commit, "author", "") or "").strip().lower()
        if author:
            counts[author] = counts.get(author, 0) + 1
    if not counts:
        return SignalContribution("author_expertise", 0.0, weight).finalize()
    expert, expert_count = max(counts.items(), key=lambda item: item[1])
    total = sum(counts.values())
    ratio = expert_count / max(total, 1)
    value = min(1.0, ratio + (0.15 if expert_count >= 3 else 0.0))
    return SignalContribution(
        "author_expertise",
        value,
        weight,
        evidence={"expert_author": expert, "expertise_ratio": round(ratio, 4), "expert_commits": expert_count},
    ).finalize()


def compute_mcp_signal_engine_v2(
    path: str,
    unified_context: Any | None,
    *,
    mcp_graph_context: dict[str, Any] | None = None,
    service_name: str = "",
    anomaly_timestamp: str | None = None,
    error_keywords: list[str] | None = None,
) -> dict[str, SignalContribution]:
    """
    Compute all MCP Signal Engine v2 contributions for one candidate path.

    Returns a dict keyed by signal name with value, weight, contribution, evidence.
    """
    if not mcp_signal_v2_enabled() or unified_context is None:
        return _empty_contributions()

    commits = _model_list(unified_context, "commits")
    pull_requests = _model_list(unified_context, "pull_requests")
    deployments = _model_list(unified_context, "deployment_events") + _model_list(
        unified_context, "jenkins_deployment_events"
    )
    builds = _model_list(unified_context, "build_events")
    alerts = _model_list(unified_context, "alert_events")
    metrics = _model_list(unified_context, "metric_events")
    traces = _model_list(unified_context, "trace_events")
    incidents = _model_list(unified_context, "pagerduty_incidents")

    touching_commits = _commits_touching_path(path, commits)
    touching_prs = _prs_touching_path(path, pull_requests)
    anchor = _anchor_time(anomaly_timestamp=anomaly_timestamp, unified_context=unified_context)
    keywords = list(error_keywords or [])

    contributions = {
        "code_ownership": _compute_code_ownership(path, touching_commits, touching_prs),
        "code_churn": _compute_code_churn(path, touching_commits, anchor),
        "deployment_proximity_v2": _compute_deployment_proximity_v2(path, touching_commits, deployments, anchor),
        "rollback": _compute_rollback(path, touching_commits, deployments),
        "build_failure": _compute_build_failure(path, touching_commits, builds),
        "service_dependency": _compute_service_dependency(
            path, service_name, alerts, incidents, traces, keywords
        ),
        "incident_recurrence": _compute_incident_recurrence(path, service_name, keywords, mcp_graph_context),
        "alert_correlation_v2": _compute_alert_correlation_v2(path, service_name, alerts, metrics, traces),
        "reviewer": _compute_reviewer(path, touching_prs),
        "author_expertise": _compute_author_expertise(path, commits),
    }
    return contributions


def contributions_to_signal_values(contributions: dict[str, SignalContribution]) -> dict[str, float]:
    return {name: contrib.value for name, contrib in contributions.items()}


def contributions_to_bundle_fields(
    contributions: dict[str, SignalContribution],
    *,
    candidate_path: str = "",
) -> dict[str, Any]:
    """Serialize v2 signals for evidence bundle persistence."""
    signals = []
    for name in MCP_SIGNAL_V2_NAMES:
        contrib = contributions.get(name)
        if contrib is None:
            continue
        signals.append(
            {
                "name": name,
                "value": contrib.value,
                "weight": contrib.weight,
                "contribution": contrib.contribution,
                "evidence": dict(contrib.evidence),
            }
        )
    return {
        "mcp_signal_engine_v2": {
            "schema_version": "2.0.0",
            "candidate_path": candidate_path,
            "signals": signals,
        }
    }


def jira_log_v2_boost(contributions: dict[str, SignalContribution]) -> float:
    """Additive boost for jira_log ranking from v2 signals."""
    if not contributions:
        return 0.0
    boost = 0.0
    for name, weight in JIRA_LOG_V2_BOOST_WEIGHTS.items():
        contrib = contributions.get(name)
        if contrib and contrib.value > 0:
            boost += contrib.value * weight
    return min(JIRA_LOG_V2_BOOST_CAP, boost)


def format_v2_explanation_snippet(contributions: dict[str, SignalContribution]) -> str:
    """Short deterministic explanation fragment for GraphRAG / jira_log."""
    bits: list[str] = []
    for name in MCP_SIGNAL_V2_NAMES:
        contrib = contributions.get(name)
        if not contrib or contrib.value <= 0:
            continue
        bits.append(f"{name}={contrib.value:.2f} (contrib {contrib.contribution:.3f})")
    if not bits:
        return ""
    return "MCP Signal Engine v2: " + "; ".join(bits[:6]) + "."
