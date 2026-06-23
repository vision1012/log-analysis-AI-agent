"""
Pre-built conference demo investigation scenarios.

Each scenario includes realistic Jira, GitHub, build, deployment, Datadog, PagerDuty,
runbook, RCA, and confidence data for live demos without modifying RCA or GraphRAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from demo.demo_models import DemoFeedbackSeed, DemoScenario
from mcp.context.investigation_context import UnifiedInvestigationContext
from mcp.schemas.confluence_models import RunbookDocument
from mcp.schemas.datadog_models import AlertEvent, MetricEvent, TraceEvent
from mcp.schemas.github_models import McpCommit, McpPullRequest
from mcp.schemas.jenkins_models import BuildEvent, DeploymentEvent
from mcp.schemas.jira_models import McpTicketContext
from mcp.schemas.kubernetes_models import ContainerEvent, PodEvent
from mcp.schemas.pagerduty_models import PagerDutyIncidentEvent


@dataclass(frozen=True)
class _ScenarioBundle:
    scenario: DemoScenario
    build_context: Callable[[], UnifiedInvestigationContext]
    feedback_seed: DemoFeedbackSeed | None = None


def _timeline_event(
    *,
    event_type: str,
    source: str,
    title: str,
    timestamp: str,
    description: str = "",
    severity: str = "",
) -> dict[str, str]:
    return {
        "event_type": event_type,
        "source": source,
        "title": title,
        "timestamp": timestamp,
        "description": description,
        "severity": severity,
    }


def _similar_incident(
    *,
    investigation_id: str,
    similarity_score: float,
    root_cause: str,
    resolution_summary: str,
) -> dict[str, object]:
    return {
        "investigation_id": investigation_id,
        "similarity_score": similarity_score,
        "root_cause": root_cause,
        "resolution_summary": resolution_summary,
        "matched_factors": ["service_match", "alert_match"],
    }


def _graph_summary(**counts: int | list[str]) -> dict[str, object]:
    return counts


def _auth_failure_bundle() -> _ScenarioBundle:
    service = "auth-service"
    ticket_key = "OPS-101"
    root_cause = "/srv/auth/handler.py"
    base = "2024-06-15T"

    scenario = DemoScenario(
        scenario_id="auth-failure",
        title="Authentication Failure",
        description=(
            "Spike in 401/500 errors after a merged PR changed token validation logic. "
            "Engineers correlate Jira, GitHub, deployment, Datadog alerts, and PagerDuty."
        ),
        service_name=service,
        severity="critical",
        ticket_key=ticket_key,
        root_cause=root_cause,
        resolution="Rolled back deployment and reverted PR #842; restored JWT clock skew tolerance.",
        confidence=0.88,
        timeline_events=[
            _timeline_event(event_type="JIRA_CREATED", source="Jira", title="Users cannot sign in", timestamp=f"{base}08:00:00Z", severity="High"),
            _timeline_event(event_type="PR_MERGED", source="GitHub", title="PR #842: tighten JWT validation", timestamp=f"{base}09:15:00Z"),
            _timeline_event(event_type="COMMIT_PUSHED", source="GitHub", title="tighten JWT validation", timestamp=f"{base}09:10:00Z"),
            _timeline_event(event_type="BUILD_STARTED", source="Jenkins", title="Build #441 started", timestamp=f"{base}09:20:00Z"),
            _timeline_event(event_type="BUILD_COMPLETED", source="Jenkins", title="Build #441 completed", timestamp=f"{base}09:28:00Z"),
            _timeline_event(event_type="DEPLOYMENT_COMPLETED", source="Jenkins", title="Deployment to prod completed", timestamp=f"{base}09:35:00Z"),
            _timeline_event(event_type="METRIC_SPIKE", source="Datadog", title="Metric spike: error_rate", timestamp=f"{base}09:42:00Z", severity="critical"),
            _timeline_event(event_type="ALERT_TRIGGERED", source="Datadog", title="Auth error rate critical", timestamp=f"{base}09:45:00Z", severity="critical"),
            _timeline_event(event_type="INCIDENT_OPENED", source="PagerDuty", title="Auth service outage", timestamp=f"{base}09:48:00Z", severity="high"),
            _timeline_event(event_type="RUNBOOK_MATCHED", source="Confluence", title="auth-service incident runbook", timestamp=f"{base}09:50:00Z"),
            _timeline_event(event_type="RCA_COMPLETED", source="RCA", title="RCA completed", timestamp=f"{base}10:05:00Z"),
            _timeline_event(event_type="FEEDBACK_SUBMITTED", source="Feedback", title="Feedback submitted: confirmed", timestamp=f"{base}10:20:00Z"),
        ],
        graph_entities=_graph_summary(
            jira_tickets=1,
            pull_requests=1,
            commits=1,
            builds=1,
            deployments=1,
            metrics=1,
            alerts=1,
            pagerduty_incidents=1,
            runbooks=1,
            services=[service],
        ),
        similar_incidents=[
            _similar_incident(
                investigation_id="demo-hist-auth-2024-03",
                similarity_score=0.74,
                root_cause="/srv/auth/token_validator.py",
                resolution_summary="JWT clock skew misconfiguration — status: completed",
            )
        ],
    )

    def build_context() -> UnifiedInvestigationContext:
        return UnifiedInvestigationContext(
            ticket_context=McpTicketContext(
                issue_key=ticket_key,
                summary="Users cannot sign in — auth-service error spike",
                status="In Progress",
                priority="High",
                url=f"https://demo.atlassian.net/browse/{ticket_key}",
            ),
            pull_requests=[
                McpPullRequest(
                    number=842,
                    title="Tighten JWT validation",
                    state="merged",
                    merged=True,
                    merged_at=f"{base}09:15:00Z",
                    author="alex.chen",
                    url="https://github.com/acme/platform/pull/842",
                )
            ],
            commits=[
                McpCommit(
                    sha="a1b2c3d4e5f6",
                    message="Tighten JWT validation",
                    author="alex.chen",
                    committed_at=f"{base}09:10:00Z",
                    changed_files=[root_cause],
                )
            ],
            build_events=[
                BuildEvent(
                    build_id="build-auth-441",
                    build_number=441,
                    status="SUCCESS",
                    branch="main",
                    commit_sha="a1b2c3d4e5f6",
                    started_at=f"{base}09:20:00Z",
                    completed_at=f"{base}09:28:00Z",
                    build_url="https://jenkins.acme.io/job/auth-service/441",
                )
            ],
            deployment_events=[
                DeploymentEvent(
                    deployment_id="dep-auth-prod-441",
                    environment="prod",
                    status="SUCCESS",
                    commit_sha="a1b2c3d4e5f6",
                    deployed_at=f"{base}09:35:00Z",
                    deployment_url="https://jenkins.acme.io/job/auth-service/441/deploy",
                )
            ],
            metric_events=[
                MetricEvent(
                    metric_name="error_rate",
                    service=service,
                    value=18.4,
                    unit="percent",
                    severity="critical",
                    timestamp=f"{base}09:42:00Z",
                )
            ],
            alert_events=[
                AlertEvent(
                    alert_id="alert-auth-err-1",
                    title="Auth error rate critical",
                    message="5xx rate above 15% for auth-service",
                    service=service,
                    severity="critical",
                    status="triggered",
                    triggered_at=f"{base}09:45:00Z",
                )
            ],
            pagerduty_incidents=[
                PagerDutyIncidentEvent(
                    incident_id="PD-AUTH-9001",
                    incident_number=9001,
                    title="Auth service outage",
                    service_name=service,
                    urgency="high",
                    status="acknowledged",
                    created_at=f"{base}09:48:00Z",
                    html_url="https://acme.pagerduty.com/incidents/9001",
                )
            ],
            runbook_documents=[
                RunbookDocument(
                    document_id="RB-AUTH-1",
                    title="auth-service incident runbook",
                    space_key="OPS",
                    url="https://demo.atlassian.net/wiki/spaces/OPS/pages/auth-runbook",
                    service_name=service,
                    summary="Rollback auth-service and validate JWT issuer settings.",
                    updated_at=f"{base}09:50:00Z",
                )
            ],
        )

    return _ScenarioBundle(
        scenario=scenario,
        build_context=build_context,
        feedback_seed=DemoFeedbackSeed(
            candidate_id=root_cause,
            comments="Token validator regression matches deploy window.",
        ),
    )


def _k8s_oom_bundle() -> _ScenarioBundle:
    service = "checkout-worker"
    ticket_key = "OPS-202"
    root_cause = "/app/workers/checkout_processor.py"
    base = "2024-06-16T"

    scenario = DemoScenario(
        scenario_id="k8s-oomkilled",
        title="Kubernetes OOMKilled",
        description=(
            "Checkout worker pods OOMKilled after memory limit reduction in Helm values. "
            "Kubernetes events, deployment timing, and Datadog memory metrics align."
        ),
        service_name=service,
        severity="high",
        ticket_key=ticket_key,
        root_cause=root_cause,
        resolution="Increased memory limits to 1Gi and reverted Helm chart commit.",
        confidence=0.91,
        timeline_events=[
            _timeline_event(event_type="JIRA_CREATED", source="Jira", title="Checkout jobs stalling", timestamp=f"{base}07:30:00Z", severity="High"),
            _timeline_event(event_type="COMMIT_PUSHED", source="GitHub", title="Reduce worker memory limits", timestamp=f"{base}08:00:00Z"),
            _timeline_event(event_type="BUILD_COMPLETED", source="Jenkins", title="Build #220 completed", timestamp=f"{base}08:15:00Z"),
            _timeline_event(event_type="DEPLOYMENT_COMPLETED", source="Jenkins", title="Deployment to prod completed", timestamp=f"{base}08:25:00Z"),
            _timeline_event(event_type="POD_RESTART", source="Kubernetes", title="Pod restart: checkout-worker-7d8f", timestamp=f"{base}08:35:00Z", severity="medium"),
            _timeline_event(event_type="OOM_KILLED", source="Kubernetes", title="OOM killed: checkout-worker", timestamp=f"{base}08:36:00Z", severity="high"),
            _timeline_event(event_type="METRIC_SPIKE", source="Datadog", title="Metric spike: memory.usage", timestamp=f"{base}08:37:00Z", severity="high"),
            _timeline_event(event_type="ALERT_TRIGGERED", source="Datadog", title="Pod OOMKilled alert", timestamp=f"{base}08:38:00Z", severity="high"),
            _timeline_event(event_type="INCIDENT_OPENED", source="PagerDuty", title="Checkout worker instability", timestamp=f"{base}08:40:00Z"),
            _timeline_event(event_type="RUNBOOK_MATCHED", source="Confluence", title="K8s OOM remediation runbook", timestamp=f"{base}08:42:00Z"),
            _timeline_event(event_type="RCA_COMPLETED", source="RCA", title="RCA completed", timestamp=f"{base}09:00:00Z"),
        ],
        graph_entities=_graph_summary(
            jira_tickets=1,
            commits=1,
            builds=1,
            deployments=1,
            pods=1,
            containers=1,
            metrics=1,
            alerts=1,
            pagerduty_incidents=1,
            runbooks=1,
            services=[service],
        ),
        similar_incidents=[
            _similar_incident(
                investigation_id="demo-hist-oom-2024-01",
                similarity_score=0.81,
                root_cause="/app/workers/batch_processor.py",
                resolution_summary="Memory limit too low after chart change — status: completed",
            )
        ],
    )

    def build_context() -> UnifiedInvestigationContext:
        return UnifiedInvestigationContext(
            ticket_context=McpTicketContext(
                issue_key=ticket_key,
                summary="Checkout jobs stalling — worker pods OOMKilled",
                status="Open",
                priority="High",
            ),
            commits=[
                McpCommit(
                    sha="oom111222333",
                    message="Reduce worker memory limits",
                    author="sam.lee",
                    committed_at=f"{base}08:00:00Z",
                )
            ],
            build_events=[
                BuildEvent(
                    build_id="build-checkout-220",
                    build_number=220,
                    status="SUCCESS",
                    commit_sha="oom111222333",
                    started_at=f"{base}08:10:00Z",
                    completed_at=f"{base}08:15:00Z",
                )
            ],
            deployment_events=[
                DeploymentEvent(
                    deployment_id="dep-checkout-prod-220",
                    environment="prod",
                    status="SUCCESS",
                    commit_sha="oom111222333",
                    deployed_at=f"{base}08:25:00Z",
                )
            ],
            metric_events=[
                MetricEvent(
                    metric_name="memory.usage",
                    service=service,
                    value=99.2,
                    unit="percent",
                    severity="high",
                    timestamp=f"{base}08:37:00Z",
                )
            ],
            alert_events=[
                AlertEvent(
                    alert_id="alert-oom-1",
                    title="Pod OOMKilled alert",
                    message="checkout-worker container terminated OOMKilled",
                    service=service,
                    severity="high",
                    triggered_at=f"{base}08:38:00Z",
                )
            ],
            pod_events=[
                PodEvent(
                    pod_name="checkout-worker-7d8f",
                    namespace="prod",
                    node_name="node-pool-2",
                    status="Running",
                    restart_count=3,
                    reason="OOMKilled",
                    timestamp=f"{base}08:35:00Z",
                )
            ],
            container_events=[
                ContainerEvent(
                    container_name="checkout-worker",
                    pod_name="checkout-worker-7d8f",
                    status="Terminated",
                    reason="OOMKilled",
                    timestamp=f"{base}08:36:00Z",
                )
            ],
            pagerduty_incidents=[
                PagerDutyIncidentEvent(
                    incident_id="PD-OOM-2201",
                    incident_number=2201,
                    title="Checkout worker instability",
                    service_name=service,
                    urgency="high",
                    status="triggered",
                    created_at=f"{base}08:40:00Z",
                )
            ],
            runbook_documents=[
                RunbookDocument(
                    document_id="RB-K8S-OOM",
                    title="K8s OOM remediation runbook",
                    space_key="OPS",
                    service_name=service,
                    summary="Increase limits and inspect recent Helm changes.",
                    updated_at=f"{base}08:42:00Z",
                )
            ],
        )

    return _ScenarioBundle(
        scenario=scenario,
        build_context=build_context,
        feedback_seed=DemoFeedbackSeed(candidate_id=root_cause, comments="OOM aligns with memory limit deploy."),
    )


def _db_connection_bundle() -> _ScenarioBundle:
    service = "billing-api"
    ticket_key = "OPS-303"
    root_cause = "/srv/billing/db_pool.py"
    base = "2024-06-17T"

    scenario = DemoScenario(
        scenario_id="db-connection-exhaustion",
        title="Database Connection Exhaustion",
        description=(
            "Billing API exhausts Postgres connection pool after a connection leak in a background job. "
            "Latency metrics, traces, and alerts converge on the pool manager module."
        ),
        service_name=service,
        severity="critical",
        ticket_key=ticket_key,
        root_cause=root_cause,
        resolution="Patched connection leak, restarted pods, and lowered pool max concurrency temporarily.",
        confidence=0.86,
        timeline_events=[
            _timeline_event(event_type="JIRA_CREATED", source="Jira", title="Billing timeouts", timestamp=f"{base}10:00:00Z", severity="Critical"),
            _timeline_event(event_type="PR_MERGED", source="GitHub", title="PR #119: async invoice sync", timestamp=f"{base}11:00:00Z"),
            _timeline_event(event_type="BUILD_COMPLETED", source="Jenkins", title="Build #512 completed", timestamp=f"{base}11:20:00Z"),
            _timeline_event(event_type="DEPLOYMENT_COMPLETED", source="Jenkins", title="Deployment completed", timestamp=f"{base}11:35:00Z"),
            _timeline_event(event_type="METRIC_SPIKE", source="Datadog", title="Metric spike: db.connections.active", timestamp=f"{base}11:50:00Z", severity="critical"),
            _timeline_event(event_type="TRACE_FAILURE", source="Datadog", title="Trace failures on /v1/invoices", timestamp=f"{base}11:52:00Z", severity="high"),
            _timeline_event(event_type="ALERT_TRIGGERED", source="Datadog", title="DB pool saturation", timestamp=f"{base}11:55:00Z", severity="critical"),
            _timeline_event(event_type="INCIDENT_OPENED", source="PagerDuty", title="Billing API degraded", timestamp=f"{base}11:58:00Z"),
            _timeline_event(event_type="RUNBOOK_MATCHED", source="Confluence", title="Database connection exhaustion playbook", timestamp=f"{base}12:00:00Z"),
            _timeline_event(event_type="RCA_COMPLETED", source="RCA", title="RCA completed", timestamp=f"{base}12:20:00Z"),
        ],
        graph_entities=_graph_summary(
            jira_tickets=1,
            pull_requests=1,
            builds=1,
            deployments=1,
            metrics=1,
            traces=1,
            alerts=1,
            pagerduty_incidents=1,
            runbooks=1,
            services=[service],
        ),
        similar_incidents=[
            _similar_incident(
                investigation_id="demo-hist-db-2023-11",
                similarity_score=0.69,
                root_cause="/srv/billing/invoice_sync.py",
                resolution_summary="Connection leak in batch job — status: completed",
            )
        ],
    )

    def build_context() -> UnifiedInvestigationContext:
        return UnifiedInvestigationContext(
            ticket_context=McpTicketContext(
                issue_key=ticket_key,
                summary="Billing API timeouts — database connection pool exhausted",
                status="In Progress",
                priority="Critical",
            ),
            pull_requests=[
                McpPullRequest(
                    number=119,
                    title="Async invoice sync",
                    state="merged",
                    merged=True,
                    merged_at=f"{base}11:00:00Z",
                    url="https://github.com/acme/billing/pull/119",
                )
            ],
            commits=[
                McpCommit(
                    sha="dbpool999aaa",
                    message="Add async invoice sync job",
                    author="riley.ng",
                    committed_at=f"{base}10:55:00Z",
                    changed_files=[root_cause, "/srv/billing/invoice_sync.py"],
                )
            ],
            build_events=[
                BuildEvent(
                    build_id="build-billing-512",
                    build_number=512,
                    status="SUCCESS",
                    commit_sha="dbpool999aaa",
                    completed_at=f"{base}11:20:00Z",
                )
            ],
            deployment_events=[
                DeploymentEvent(
                    deployment_id="dep-billing-prod-512",
                    environment="prod",
                    status="SUCCESS",
                    commit_sha="dbpool999aaa",
                    deployed_at=f"{base}11:35:00Z",
                )
            ],
            metric_events=[
                MetricEvent(
                    metric_name="db.connections.active",
                    service=service,
                    value=200.0,
                    unit="connections",
                    severity="critical",
                    timestamp=f"{base}11:50:00Z",
                )
            ],
            trace_events=[
                TraceEvent(
                    trace_id="trace-billing-1",
                    service=service,
                    endpoint="/v1/invoices",
                    latency_ms=4500.0,
                    error_count=28,
                    timestamp=f"{base}11:52:00Z",
                )
            ],
            alert_events=[
                AlertEvent(
                    alert_id="alert-db-pool-1",
                    title="DB pool saturation",
                    message="Active connections at pool maximum",
                    service=service,
                    severity="critical",
                    triggered_at=f"{base}11:55:00Z",
                )
            ],
            pagerduty_incidents=[
                PagerDutyIncidentEvent(
                    incident_id="PD-DB-3303",
                    incident_number=3303,
                    title="Billing API degraded",
                    service_name=service,
                    urgency="high",
                    status="acknowledged",
                    created_at=f"{base}11:58:00Z",
                )
            ],
            runbook_documents=[
                RunbookDocument(
                    document_id="RB-DB-POOL",
                    title="Database connection exhaustion playbook",
                    space_key="OPS",
                    service_name=service,
                    summary="Drain connections, identify leak, rollback if needed.",
                    updated_at=f"{base}12:00:00Z",
                )
            ],
        )

    return _ScenarioBundle(
        scenario=scenario,
        build_context=build_context,
        feedback_seed=DemoFeedbackSeed(candidate_id=root_cause, comments="Pool leak introduced in async sync deploy."),
    )


def _payment_deploy_bundle() -> _ScenarioBundle:
    service = "payment-service"
    ticket_key = "OPS-404"
    root_cause = "/srv/payment/deploy/helm_values.yaml"
    base = "2024-06-18T"

    scenario = DemoScenario(
        scenario_id="payment-deploy-failure",
        title="Payment Service Deployment Failure",
        description=(
            "Payment service deployment fails health checks after an incorrect feature flag default. "
            "Failed build/deploy pipeline, alerts, and incident timeline tell the story."
        ),
        service_name=service,
        severity="critical",
        ticket_key=ticket_key,
        root_cause=root_cause,
        resolution="Disabled bad feature flag default and redeployed previous chart revision.",
        confidence=0.84,
        timeline_events=[
            _timeline_event(event_type="JIRA_CREATED", source="Jira", title="Payments failing in prod", timestamp=f"{base}14:00:00Z", severity="Critical"),
            _timeline_event(event_type="COMMIT_PUSHED", source="GitHub", title="Enable new payment rail flag by default", timestamp=f"{base}14:30:00Z"),
            _timeline_event(event_type="BUILD_STARTED", source="Jenkins", title="Build #88 started", timestamp=f"{base}14:40:00Z"),
            _timeline_event(event_type="BUILD_COMPLETED", source="Jenkins", title="Build #88 completed", timestamp=f"{base}14:48:00Z"),
            _timeline_event(event_type="DEPLOYMENT_STARTED", source="Jenkins", title="Deployment to prod started", timestamp=f"{base}14:50:00Z"),
            _timeline_event(event_type="DEPLOYMENT_COMPLETED", source="Jenkins", title="Deployment to prod failed health checks", timestamp=f"{base}14:54:00Z", severity="critical"),
            _timeline_event(event_type="ALERT_TRIGGERED", source="Datadog", title="Payment success rate drop", timestamp=f"{base}14:55:00Z", severity="critical"),
            _timeline_event(event_type="INCIDENT_OPENED", source="PagerDuty", title="Payment processing outage", timestamp=f"{base}14:57:00Z"),
            _timeline_event(event_type="RUNBOOK_MATCHED", source="Confluence", title="Payment service rollback runbook", timestamp=f"{base}15:00:00Z"),
            _timeline_event(event_type="RCA_COMPLETED", source="RCA", title="RCA completed", timestamp=f"{base}15:25:00Z"),
        ],
        graph_entities=_graph_summary(
            jira_tickets=1,
            commits=1,
            builds=1,
            deployments=1,
            alerts=1,
            pagerduty_incidents=1,
            runbooks=1,
            services=[service],
        ),
        similar_incidents=[
            _similar_incident(
                investigation_id="demo-hist-pay-2024-02",
                similarity_score=0.77,
                root_cause="/srv/payment/config/feature_flags.py",
                resolution_summary="Bad feature flag default — status: completed",
            )
        ],
    )

    def build_context() -> UnifiedInvestigationContext:
        return UnifiedInvestigationContext(
            ticket_context=McpTicketContext(
                issue_key=ticket_key,
                summary="Payments failing in prod after deployment",
                status="Open",
                priority="Critical",
            ),
            commits=[
                McpCommit(
                    sha="payflag777bbb",
                    message="Enable new payment rail flag by default",
                    author="jordan.kim",
                    committed_at=f"{base}14:30:00Z",
                    changed_files=[root_cause, "/srv/payment/config/feature_flags.py"],
                )
            ],
            build_events=[
                BuildEvent(
                    build_id="build-payment-88",
                    build_number=88,
                    status="SUCCESS",
                    commit_sha="payflag777bbb",
                    started_at=f"{base}14:40:00Z",
                    completed_at=f"{base}14:48:00Z",
                )
            ],
            deployment_events=[
                DeploymentEvent(
                    deployment_id="dep-payment-prod-88",
                    environment="prod",
                    status="FAILED",
                    commit_sha="payflag777bbb",
                    deployed_at=f"{base}14:50:00Z",
                )
            ],
            alert_events=[
                AlertEvent(
                    alert_id="alert-pay-success-1",
                    title="Payment success rate drop",
                    message="Success rate below 70%",
                    service=service,
                    severity="critical",
                    triggered_at=f"{base}14:55:00Z",
                )
            ],
            pagerduty_incidents=[
                PagerDutyIncidentEvent(
                    incident_id="PD-PAY-4404",
                    incident_number=4404,
                    title="Payment processing outage",
                    service_name=service,
                    urgency="high",
                    status="triggered",
                    created_at=f"{base}14:57:00Z",
                )
            ],
            runbook_documents=[
                RunbookDocument(
                    document_id="RB-PAY-ROLLBACK",
                    title="Payment service rollback runbook",
                    space_key="OPS",
                    service_name=service,
                    summary="Rollback chart revision and disable payment rail flag.",
                    updated_at=f"{base}15:00:00Z",
                )
            ],
        )

    return _ScenarioBundle(
        scenario=scenario,
        build_context=build_context,
        feedback_seed=DemoFeedbackSeed(
            feedback_type="OVERRIDDEN",
            candidate_id=root_cause,
            override_candidate_id="/srv/payment/config/feature_flags.py",
            comments="Flag config was wrong; actual issue in feature_flags.py",
        ),
    )


def _api_latency_bundle() -> _ScenarioBundle:
    service = "catalog-api"
    ticket_key = "OPS-505"
    root_cause = "/srv/catalog/search/query_builder.py"
    base = "2024-06-19T"

    scenario = DemoScenario(
        scenario_id="api-latency-regression",
        title="API Latency Regression",
        description=(
            "Catalog API p99 latency regression after an N+1 query change. "
            "Traces, metrics, and merged PR data highlight the search query builder."
        ),
        service_name=service,
        severity="high",
        ticket_key=ticket_key,
        root_cause=root_cause,
        resolution="Reverted query builder change and added eager loading for product facets.",
        confidence=0.89,
        timeline_events=[
            _timeline_event(event_type="JIRA_CREATED", source="Jira", title="Catalog search slow", timestamp=f"{base}09:00:00Z", severity="High"),
            _timeline_event(event_type="PR_MERGED", source="GitHub", title="PR #256: optimize facet queries", timestamp=f"{base}09:30:00Z"),
            _timeline_event(event_type="COMMIT_PUSHED", source="GitHub", title="Optimize facet queries", timestamp=f"{base}09:25:00Z"),
            _timeline_event(event_type="BUILD_COMPLETED", source="Jenkins", title="Build #133 completed", timestamp=f"{base}09:45:00Z"),
            _timeline_event(event_type="DEPLOYMENT_COMPLETED", source="Jenkins", title="Deployment completed", timestamp=f"{base}10:00:00Z"),
            _timeline_event(event_type="METRIC_SPIKE", source="Datadog", title="Metric spike: trace.duration.p99", timestamp=f"{base}10:10:00Z", severity="high"),
            _timeline_event(event_type="TRACE_FAILURE", source="Datadog", title="Trace failures on /search", timestamp=f"{base}10:12:00Z", severity="medium"),
            _timeline_event(event_type="ALERT_TRIGGERED", source="Datadog", title="Catalog API latency SLO breach", timestamp=f"{base}10:15:00Z", severity="high"),
            _timeline_event(event_type="INCIDENT_OPENED", source="PagerDuty", title="Catalog latency regression", timestamp=f"{base}10:18:00Z"),
            _timeline_event(event_type="RUNBOOK_MATCHED", source="Confluence", title="API latency investigation guide", timestamp=f"{base}10:20:00Z"),
            _timeline_event(event_type="RCA_COMPLETED", source="RCA", title="RCA completed", timestamp=f"{base}10:40:00Z"),
        ],
        graph_entities=_graph_summary(
            jira_tickets=1,
            pull_requests=1,
            commits=1,
            builds=1,
            deployments=1,
            metrics=1,
            traces=1,
            alerts=1,
            pagerduty_incidents=1,
            runbooks=1,
            services=[service],
        ),
        similar_incidents=[
            _similar_incident(
                investigation_id="demo-hist-latency-2024-04",
                similarity_score=0.71,
                root_cause="/srv/catalog/search/facet_loader.py",
                resolution_summary="N+1 query regression — status: completed",
            )
        ],
    )

    def build_context() -> UnifiedInvestigationContext:
        return UnifiedInvestigationContext(
            ticket_context=McpTicketContext(
                issue_key=ticket_key,
                summary="Catalog search slow — p99 latency regression",
                status="Open",
                priority="High",
            ),
            pull_requests=[
                McpPullRequest(
                    number=256,
                    title="Optimize facet queries",
                    state="merged",
                    merged=True,
                    merged_at=f"{base}09:30:00Z",
                    url="https://github.com/acme/catalog/pull/256",
                )
            ],
            commits=[
                McpCommit(
                    sha="lat256cccddd",
                    message="Optimize facet queries",
                    author="morgan.patel",
                    committed_at=f"{base}09:25:00Z",
                    changed_files=[root_cause],
                )
            ],
            build_events=[
                BuildEvent(
                    build_id="build-catalog-133",
                    build_number=133,
                    status="SUCCESS",
                    commit_sha="lat256cccddd",
                    completed_at=f"{base}09:45:00Z",
                )
            ],
            deployment_events=[
                DeploymentEvent(
                    deployment_id="dep-catalog-prod-133",
                    environment="prod",
                    status="SUCCESS",
                    commit_sha="lat256cccddd",
                    deployed_at=f"{base}10:00:00Z",
                )
            ],
            metric_events=[
                MetricEvent(
                    metric_name="trace.duration.p99",
                    service=service,
                    value=2800.0,
                    unit="ms",
                    severity="high",
                    timestamp=f"{base}10:10:00Z",
                )
            ],
            trace_events=[
                TraceEvent(
                    trace_id="trace-catalog-1",
                    service=service,
                    endpoint="/search",
                    latency_ms=2800.0,
                    error_count=6,
                    timestamp=f"{base}10:12:00Z",
                )
            ],
            alert_events=[
                AlertEvent(
                    alert_id="alert-latency-1",
                    title="Catalog API latency SLO breach",
                    message="p99 above 2s for 10 minutes",
                    service=service,
                    severity="high",
                    triggered_at=f"{base}10:15:00Z",
                )
            ],
            pagerduty_incidents=[
                PagerDutyIncidentEvent(
                    incident_id="PD-CAT-5505",
                    incident_number=5505,
                    title="Catalog latency regression",
                    service_name=service,
                    urgency="low",
                    status="acknowledged",
                    created_at=f"{base}10:18:00Z",
                )
            ],
            runbook_documents=[
                RunbookDocument(
                    document_id="RB-LATENCY",
                    title="API latency investigation guide",
                    space_key="OPS",
                    service_name=service,
                    summary="Compare deploy time with trace and DB query metrics.",
                    updated_at=f"{base}10:20:00Z",
                )
            ],
        )

    return _ScenarioBundle(
        scenario=scenario,
        build_context=build_context,
        feedback_seed=DemoFeedbackSeed(candidate_id=root_cause, comments="N+1 regression in query builder."),
    )


_SCENARIO_BUNDLES: dict[str, _ScenarioBundle] = {
    bundle.scenario.scenario_id: bundle
    for bundle in [
        _auth_failure_bundle(),
        _k8s_oom_bundle(),
        _db_connection_bundle(),
        _payment_deploy_bundle(),
        _api_latency_bundle(),
    ]
}


def all_scenario_bundles() -> dict[str, _ScenarioBundle]:
    return dict(_SCENARIO_BUNDLES)


def get_scenario_bundle(scenario_id: str) -> _ScenarioBundle:
    key = (scenario_id or "").strip()
    if key not in _SCENARIO_BUNDLES:
        raise KeyError(f"unknown demo scenario: {scenario_id}")
    return _SCENARIO_BUNDLES[key]
