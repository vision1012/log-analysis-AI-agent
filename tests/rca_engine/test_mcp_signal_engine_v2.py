"""Unit tests for Deterministic MCP Signal Engine v2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent
from rca_engine.mcp_signal_engine_v2 import (
    compute_mcp_signal_engine_v2,
    contributions_to_bundle_fields,
    jira_log_v2_boost,
)
from rca_engine.mcp_signal_v2_config import MCP_SIGNAL_V2_NAMES

PATH = "/app/src/api/http/parseIntegrationsApi.ts"
ANCHOR = datetime(2026, 6, 24, 10, 0, 3, tzinfo=timezone.utc)


def _commit(sha: str, author: str, days_ago: int, files: list[str]) -> McpCommit:
    ts = (ANCHOR - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return McpCommit(sha=sha, author=author, message=f"change {files[0]}", committed_at=ts, changed_files=files)


def _base_context(**kwargs) -> UnifiedInvestigationContext:
    defaults = dict(
        commits=[
            _commit("aaa111", "dev1", 2, ["src/api/http/parseIntegrationsApi.ts"]),
            _commit("bbb222", "dev1", 5, ["src/api/http/parseIntegrationsApi.ts"]),
            _commit("ccc333", "dev2", 20, ["README.md"]),
        ],
        pull_requests=[
            McpPullRequest(
                number=3,
                author="dev1",
                title="Wire integrations",
                changed_files=["src/api/http/parseIntegrationsApi.ts"],
                reviewers=["reviewer1", "reviewer2"],
            )
        ],
    )
    defaults.update(kwargs)
    return UnifiedInvestigationContext(**defaults)


def test_all_signal_names_present() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    assert set(contribs.keys()) == set(MCP_SIGNAL_V2_NAMES)


def test_code_ownership_high_for_dominant_author() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    sig = contribs["code_ownership"]
    assert sig.value >= 0.5
    assert sig.contribution == round(sig.value * sig.weight, 6)
    assert sig.evidence.get("primary_owner") == "dev1"


def test_code_churn_counts_recent_commits() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    sig = contribs["code_churn"]
    assert sig.value > 0
    assert sig.evidence["churn_counts"][7] >= 1


def test_deployment_proximity_v2_near_anchor() -> None:
    ctx = _base_context(
        deployment_events=[
            DeploymentEvent(
                deployment_id="dep-1",
                commit_sha="aaa111",
                deployed_at=(ANCHOR - timedelta(minutes=8)).isoformat().replace("+00:00", "Z"),
                status="success",
            )
        ]
    )
    contribs = compute_mcp_signal_engine_v2(PATH, ctx, anomaly_timestamp=ANCHOR.isoformat())
    assert contribs["deployment_proximity_v2"].value >= 0.5


def test_rollback_on_failed_deployment() -> None:
    ctx = _base_context(
        deployment_events=[
            DeploymentEvent(
                deployment_id="dep-rb",
                commit_sha="aaa111",
                deployed_at=ANCHOR.isoformat().replace("+00:00", "Z"),
                status="rollback",
            )
        ]
    )
    contribs = compute_mcp_signal_engine_v2(PATH, ctx, anomaly_timestamp=ANCHOR.isoformat())
    assert contribs["rollback"].value == 1.0


def test_build_failure_linked_commit() -> None:
    ctx = _base_context(
        build_events=[
            BuildEvent(build_id="b-1", commit_sha="aaa111", status="failed"),
        ]
    )
    contribs = compute_mcp_signal_engine_v2(PATH, ctx, anomaly_timestamp=ANCHOR.isoformat())
    assert contribs["build_failure"].value >= 0.5


def test_service_dependency_upstream_alert() -> None:
    ctx = _base_context(
        alert_events=[
            AlertEvent(alert_id="a-1", service="identity-provider", title="timeout errors", severity="high"),
        ]
    )
    contribs = compute_mcp_signal_engine_v2(
        PATH,
        ctx,
        service_name="auth-service",
        anomaly_timestamp=ANCHOR.isoformat(),
        error_keywords=["timeout"],
    )
    assert contribs["service_dependency"].value > 0


def test_incident_recurrence_prior_investigation() -> None:
    graph_ctx = {
        "previous_investigations": [
            {"investigation_id": "inv-old", "ticket_key": "LAAA-1", "root_cause": PATH},
        ]
    }
    contribs = compute_mcp_signal_engine_v2(
        PATH,
        _base_context(),
        mcp_graph_context=graph_ctx,
        service_name="auth-service",
        anomaly_timestamp=ANCHOR.isoformat(),
    )
    assert contribs["incident_recurrence"].value > 0


def test_alert_correlation_v2_metrics_and_traces() -> None:
    ctx = _base_context(
        alert_events=[
            AlertEvent(alert_id="a-2", service="auth-service", title="parseIntegrationsApi errors", severity="critical"),
        ],
        metric_events=[
            MetricEvent(metric_name="auth.errors", service="auth-service", severity="high"),
        ],
        trace_events=[
            TraceEvent(trace_id="t-1", service="auth-service", endpoint="/parseIntegrationsApi", error_count=2),
        ],
    )
    contribs = compute_mcp_signal_engine_v2(
        PATH,
        ctx,
        service_name="auth-service",
        anomaly_timestamp=ANCHOR.isoformat(),
    )
    assert contribs["alert_correlation_v2"].value >= 0.7


def test_reviewer_signal_from_pr_reviewers() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    assert contribs["reviewer"].value > 0
    assert contribs["reviewer"].evidence.get("top_reviewer")


def test_author_expertise_dominant_commit_author() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    assert contribs["author_expertise"].value > 0
    assert contribs["author_expertise"].evidence.get("expert_author") == "dev1"


def test_contributions_to_bundle_fields_shape() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    bundle = contributions_to_bundle_fields(contribs, candidate_path=PATH)
    block = bundle["mcp_signal_engine_v2"]
    assert block["schema_version"] == "2.0.0"
    assert len(block["signals"]) == len(MCP_SIGNAL_V2_NAMES)
    first = block["signals"][0]
    assert {"name", "value", "weight", "contribution", "evidence"} <= set(first.keys())


def test_jira_log_v2_boost_positive_when_signals_fire() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, _base_context(), anomaly_timestamp=ANCHOR.isoformat())
    assert jira_log_v2_boost(contribs) > 0


def test_empty_context_returns_zero_values() -> None:
    contribs = compute_mcp_signal_engine_v2(PATH, UnifiedInvestigationContext())
    assert all(c.value == 0.0 for c in contribs.values())
