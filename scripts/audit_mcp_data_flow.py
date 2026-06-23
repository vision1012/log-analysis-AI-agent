#!/usr/bin/env python3
"""
MCP End-to-End Architecture Audit — read-only static analysis.

Validates each MCP provider across registration, health, context, evidence coverage,
Neo4j persistence/retrieval, graph visualization, timeline, similar incidents,
multi-agent investigation, GraphRAG, reports, and confidence engine paths.

Does not modify runtime behavior or business logic.

Usage::

    python scripts/audit_mcp_data_flow.py
    python scripts/audit_mcp_data_flow.py --output-dir artifacts/audit
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

AuditStatus = Literal["PASS", "FAIL", "MISSING"]

DISPLAY_NAMES: dict[str, str] = {
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "jenkins": "Jenkins",
    "datadog": "Datadog",
    "kubernetes": "Kubernetes",
    "pagerduty": "PagerDuty",
    "confluence": "Confluence",
}

PROVIDERS = (
    "jira",
    "github",
    "gitlab",
    "jenkins",
    "datadog",
    "kubernetes",
    "pagerduty",
    "confluence",
)

CHECK_IDS = (
    "registry",
    "health_check",
    "context",
    "evidence_coverage",
    "neo4j_persist",
    "neo4j_retrieve",
    "graph_visualization",
    "timeline",
    "similar_incidents",
    "multi_agent",
    "graphrag",
    "investigation_report",
    "confidence_engine",
)

CHECK_LABELS: dict[str, str] = {
    "registry": "Registry",
    "health_check": "Health Check",
    "context": "UnifiedInvestigationContext",
    "evidence_coverage": "Evidence Coverage",
    "neo4j_persist": "Neo4j Persist",
    "neo4j_retrieve": "Neo4j Retrieve",
    "graph_visualization": "Graph Visualization",
    "timeline": "Timeline",
    "similar_incidents": "Similar Incidents",
    "multi_agent": "Multi-Agent Investigation",
    "graphrag": "GraphRAG Context",
    "investigation_report": "Reports",
    "confidence_engine": "Confidence Engine",
}


@dataclass
class AuditCheckResult:
    check_id: str
    label: str
    status: AuditStatus
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class ProviderAuditResult:
    provider: str
    checks: list[AuditCheckResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "FAIL")

    @property
    def missing_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "MISSING")


@dataclass
class MCPAuditReport:
    generated_at: str
    repo_root: str
    providers: list[ProviderAuditResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "summary": self.summary,
            "providers": [
                {
                    "provider": provider.provider,
                    "pass_count": provider.pass_count,
                    "fail_count": provider.fail_count,
                    "missing_count": provider.missing_count,
                    "checks": [asdict(check) for check in provider.checks],
                }
                for provider in self.providers
            ],
        }


def _read_text(relative_path: str) -> str:
    path = _REPO / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _file_contains(relative_path: str, pattern: str) -> bool:
    return pattern in _read_text(relative_path)


def _any_file_contains(relative_paths: list[str], patterns: list[str]) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in relative_paths:
        text = _read_text(rel)
        if not text:
            continue
        for pattern in patterns:
            if pattern in text:
                evidence.append(f"{rel}: {pattern}")
    return bool(evidence), evidence


def _all_files_contain(relative_paths: list[str], patterns: list[str]) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in relative_paths:
        text = _read_text(rel)
        if not text:
            return False, evidence
        for pattern in patterns:
            if pattern not in text:
                return False, evidence
            evidence.append(f"{rel}: {pattern}")
    return True, evidence


def _check_registry(provider: str) -> AuditCheckResult:
    try:
        from mcp.registry import get_provider_class, registered_sources

        if provider not in registered_sources():
            return AuditCheckResult(
                "registry",
                CHECK_LABELS["registry"],
                "FAIL",
                f"{provider} not in registered_sources()",
            )
        cls = get_provider_class(provider)  # type: ignore[arg-type]
        return AuditCheckResult(
            "registry",
            CHECK_LABELS["registry"],
            "PASS",
            f"registered as {cls.__name__}",
            [f"mcp/registry.py: {cls.__name__}"],
        )
    except Exception as exc:
        return AuditCheckResult(
            "registry",
            CHECK_LABELS["registry"],
            "MISSING",
            str(exc),
        )


def _check_health(provider: str) -> AuditCheckResult:
    rel = f"mcp/providers/{provider}_provider.py"
    text = _read_text(rel)
    if not text:
        return AuditCheckResult(
            "health_check",
            CHECK_LABELS["health_check"],
            "MISSING",
            f"provider file not found: {rel}",
        )
    if "def health_check" not in text:
        return AuditCheckResult(
            "health_check",
            CHECK_LABELS["health_check"],
            "FAIL",
            "health_check method not found",
            [rel],
        )
    try:
        from mcp.registry import get_provider_class

        cls = get_provider_class(provider)  # type: ignore[arg-type]
        if not callable(getattr(cls, "health_check", None)):
            return AuditCheckResult(
                "health_check",
                CHECK_LABELS["health_check"],
                "FAIL",
                "health_check not callable on provider class",
            )
    except Exception as exc:
        return AuditCheckResult(
            "health_check",
            CHECK_LABELS["health_check"],
            "FAIL",
            str(exc),
        )
    return AuditCheckResult(
        "health_check",
        CHECK_LABELS["health_check"],
        "PASS",
        f"{cls.__name__}.health_check()",
        [rel],
    )


def _pattern_check(
    check_id: str,
    *,
    files: list[str],
    patterns_all: list[str] | None = None,
    patterns_any: list[str] | None = None,
    indirect_patterns_any: list[str] | None = None,
    partial_detail: str = "",
) -> AuditCheckResult:
    label = CHECK_LABELS[check_id]
    patterns_all = patterns_all or []
    patterns_any = patterns_any or []
    indirect_patterns_any = indirect_patterns_any or []

    if not files:
        return AuditCheckResult(check_id, label, "MISSING", "no files configured")

    existing_files = [rel for rel in files if (_REPO / rel).is_file()]
    if not existing_files:
        return AuditCheckResult(check_id, label, "MISSING", "configured files not found")

    all_ok, all_evidence = _all_files_contain(existing_files, patterns_all) if patterns_all else (True, [])
    any_ok, any_evidence = _any_file_contains(existing_files, patterns_any) if patterns_any else (True, [])
    indirect_ok, indirect_evidence = (
        _any_file_contains(existing_files, indirect_patterns_any) if indirect_patterns_any else (False, [])
    )
    evidence = list(dict.fromkeys(all_evidence + any_evidence + indirect_evidence))

    if patterns_all and patterns_any:
        primary_ok = all_ok and any_ok
    elif patterns_all:
        primary_ok = all_ok
    elif patterns_any:
        primary_ok = any_ok
    else:
        primary_ok = True

    if primary_ok:
        return AuditCheckResult(check_id, label, "PASS", detail="integration references found", evidence=evidence)

    if indirect_ok and partial_detail:
        return AuditCheckResult(check_id, label, "FAIL", detail=partial_detail, evidence=evidence)

    if evidence:
        detail = partial_detail or "partial integration detected"
        return AuditCheckResult(check_id, label, "FAIL", detail=detail, evidence=evidence)

    return AuditCheckResult(check_id, label, "MISSING", detail="no matching references found")


# Per-provider static audit rules (read-only codebase scan).
PROVIDER_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "jira": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["ticket_context"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_jira"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_jira_ticket", "context.ticket_context"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["JiraTicket", "get_previous_similar_investigations", "HAS_JIRA_TICKET"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"JiraTicket"', "HAS_JIRA_TICKET"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["JIRA_CREATED", "SOURCE_JIRA", "JiraTicket"],
        },
        "similar_incidents": {
            "files": ["graph/investigation_retriever.py", "graph/similar_incident_service.py"],
            "patterns_any": ["ticket_key", "HAS_JIRA_TICKET", "same_ticket_key"],
        },
        "graphrag": {
            "files": ["graphrag/context_packer.py", "graphrag/narrative_generator.py"],
            "patterns_any": ["previous_investigations", "ticket_key"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py", "reporting/report_models.py"],
            "patterns_any": ["evidence_coverage", "ticket_key"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"jira": "Jira"'],
        },
        "multi_agent": {
            "files": ["agents/investigation_context_loader.py", "investigation/timeline_service.py"],
            "patterns_any": ["ticket_key", "JIRA_CREATED"],
        },
    },
    "github": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["pull_requests", "commits"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_github", "McpCommit"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_pull_request", "upsert_commit", "context.pull_requests"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["PullRequest", "Commit", "get_recent_commits_for_service"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"PullRequest"', '"Commit"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["PR_MERGED", "COMMIT_PUSHED", "SOURCE_GITHUB"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Commit": "commit_match"', "commit_match"],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py", "graphrag/context_packer.py"],
            "patterns_any": ["pull_requests", "commits", "related_commits"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage", "_PROVIDER_LABELS"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"github": "GitHub"'],
        },
        "multi_agent": {
            "files": ["agents/deployment_agent.py", "investigation/timeline_service.py"],
            "patterns_any": ["PR_MERGED", "COMMIT_PUSHED", "SOURCE_GITHUB"],
        },
    },
    "gitlab": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["merge_requests", "McpGitLabCommit", "pipelines"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_gitlab", "McpGitLabCommit"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_merge_request", "upsert_deployment", "context.merge_requests"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["MergeRequest", "get_related_deployments"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"MergeRequest"', "LABEL_ALIASES"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["SOURCE_GITLAB", "MergeRequest"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Deployment": "deployment_match"', "deployment_match"],
            "partial_detail": "no GitLab-specific entity; similar search uses shared Deployment nodes",
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py"],
            "patterns_any": ["merge_requests", "deployment_events"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"gitlab": "GitLab"'],
        },
        "multi_agent": {
            "files": ["agents/deployment_agent.py", "investigation/timeline_service.py"],
            "patterns_any": ["SOURCE_GITLAB", "DEPLOYMENT_COMPLETED"],
        },
    },
    "jenkins": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["build_events", "deployment_events"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_jenkins", "BuildEvent"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_build", "context.build_events"],
        },
        "neo4j_retrieve": {
            "files": ["agents/investigation_context_loader.py", "graph/investigation_retriever.py"],
            "patterns_any": ["_fetch_builds", "Build"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Build"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["BUILD_STARTED", "BUILD_COMPLETED", "SOURCE_JENKINS"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Build": "build_match"', "build_match"],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py"],
            "patterns_any": ["build_events", "deployment_events"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage", "Missing Jenkins"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"jenkins": "Jenkins"'],
        },
        "multi_agent": {
            "files": ["agents/deployment_agent.py", "agents/investigation_context_loader.py"],
            "patterns_any": ["builds", "deployments"],
        },
    },
    "datadog": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["alert_events", "metric_events", "trace_events"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_datadog"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_alert_event", "upsert_metric_event", "context.alert_events"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_alerts", "AlertEvent", "MetricEvent"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"AlertEvent"', '"MetricEvent"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["ALERT_TRIGGERED", "METRIC_SPIKE", "SOURCE_DATADOG"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"AlertEvent": "alert_match"', "alert_match"],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py", "graphrag/context_packer.py"],
            "patterns_any": ["alert_events", "related_alerts"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage", "Missing Datadog"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"datadog": "Datadog"'],
        },
        "multi_agent": {
            "files": ["agents/incident_agent.py"],
            "patterns_any": ["Datadog alert"],
        },
    },
    "kubernetes": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["pod_events", "container_events", "node_events"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_kubernetes"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_pod", "context.pod_events"],
        },
        "neo4j_retrieve": {
            "files": ["graph/graph_visualization_service.py", "agents/investigation_context_loader.py"],
            "patterns_any": ['"Pod"', "pod_events"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Pod"', "AFFECTED_POD"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["POD_RESTART", "OOM_KILLED", "SOURCE_KUBERNETES"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": [
                "PodEvent",
                "ContainerEvent",
                "NodeEvent",
                "kubernetes_similarity_score",
                "pod_match",
                "kubernetes_signal_match",
                "K8sSignal",
                "OOMKilled",
            ],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py"],
            "patterns_any": ["pod_events"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"kubernetes": "Kubernetes"'],
        },
        "multi_agent": {
            "files": ["agents/infrastructure_agent.py", "investigation/timeline_service.py"],
            "patterns_any": ["POD_RESTART", "OOM_KILLED", "Kubernetes"],
        },
    },
    "pagerduty": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["pagerduty_incidents", "pagerduty_escalations"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_pagerduty"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_pagerduty_incident", "context.pagerduty_incidents"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_incidents", "PagerDutyIncident"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"PagerDutyIncident"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["INCIDENT_OPENED", "SOURCE_PAGERDUTY", "PagerDutyIncident"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"PagerDutyIncident": "pagerduty_incident_match"', "pagerduty_incident_match"],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py", "graphrag/context_packer.py"],
            "patterns_any": ["pagerduty_incidents", "related_incidents"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["evidence_coverage", "Missing PagerDuty"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"pagerduty": "PagerDuty"'],
        },
        "multi_agent": {
            "files": ["agents/incident_agent.py"],
            "patterns_any": ["PagerDuty incident"],
        },
    },
    "confluence": {
        "context": {
            "files": ["mcp/context/investigation_context.py", "mcp/orchestrator.py"],
            "patterns_any": ["runbook_documents", "known_issue_documents", "architecture_documents"],
        },
        "evidence_coverage": {
            "files": ["mcp/evidence_coverage.py"],
            "patterns_all": ["_contributed_confluence"],
        },
        "neo4j_persist": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_runbook", "upsert_known_issue", "context.runbook_documents"],
        },
        "neo4j_retrieve": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_runbooks_for_service", "get_known_issues_for_alert", "Runbook", "KnownIssue"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Runbook"', '"KnownIssue"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["RUNBOOK_MATCHED", "SOURCE_CONFLUENCE"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Runbook": "runbook_match"', '"KnownIssue": "known_issue_match"'],
        },
        "graphrag": {
            "files": ["graphrag/narrative_generator.py", "graphrag/context_packer.py"],
            "patterns_any": ["runbooks", "known_issues", "runbook_documents"],
        },
        "investigation_report": {
            "files": ["reporting/report_builder.py", "reporting/markdown_exporter.py"],
            "patterns_any": ["runbooks", "evidence_coverage", "Runbooks"],
        },
        "confidence_engine": {
            "files": ["rca_engine/confidence_engine.py"],
            "patterns_all": ['"confluence": "Confluence"'],
        },
        "multi_agent": {
            "files": ["agents/knowledge_agent.py"],
            "patterns_any": ["runbooks", "known_issues"],
        },
    },
}


def audit_provider(provider: str) -> ProviderAuditResult:
    """Run all audit checks for one MCP provider."""
    result = ProviderAuditResult(provider=provider)
    result.checks.append(_check_registry(provider))
    result.checks.append(_check_health(provider))

    rules = PROVIDER_RULES.get(provider, {})
    for check_id in CHECK_IDS:
        if check_id in {"registry", "health_check"}:
            continue
        rule = rules.get(check_id)
        if not rule:
            result.checks.append(
                AuditCheckResult(check_id, CHECK_LABELS[check_id], "MISSING", "no audit rule configured")
            )
            continue
        result.checks.append(
            _pattern_check(
                check_id,
                files=rule.get("files", []),
                patterns_all=rule.get("patterns_all"),
                patterns_any=rule.get("patterns_any"),
                indirect_patterns_any=rule.get("indirect_patterns_any"),
                partial_detail=rule.get("partial_detail", ""),
            )
        )
    return result


def run_audit() -> MCPAuditReport:
    """Execute the full MCP data-flow audit."""
    providers = [audit_provider(name) for name in PROVIDERS]
    summary = {"PASS": 0, "FAIL": 0, "MISSING": 0}
    for provider in providers:
        for check in provider.checks:
            summary[check.status] += 1
    return MCPAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO),
        providers=providers,
        summary=summary,
    )


def render_markdown(report: MCPAuditReport) -> str:
    """Render human-readable audit report."""
    lines = [
        "# MCP End-to-End Architecture Audit",
        "",
        f"**Generated:** {report.generated_at}",
        f"**Repository:** `{report.repo_root}`",
        "",
        "## Summary",
        "",
        f"- PASS: {report.summary.get('PASS', 0)}",
        f"- FAIL: {report.summary.get('FAIL', 0)}",
        f"- MISSING: {report.summary.get('MISSING', 0)}",
        "",
    ]
    for provider in report.providers:
        display = DISPLAY_NAMES.get(provider.provider, provider.provider.title())
        lines.extend([f"## {display}", ""])
        for check in provider.checks:
            line = f"[{check.status}] {check.label}"
            if check.detail:
                line += f" — {check.detail}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_reports(report: MCPAuditReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown audit artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "mcp_audit_report.json"
    md_path = output_dir / "mcp_audit_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def print_console_summary(report: MCPAuditReport) -> None:
    """Print concise PASS/FAIL/MISSING lines to stdout."""
    print("=== MCP End-to-End Architecture Audit ===")
    print(f"generated_at={report.generated_at}")
    print()
    for provider in report.providers:
        title = DISPLAY_NAMES.get(provider.provider, provider.provider.upper())
        print(title)
        for check in provider.checks:
            print(check.status, check.label + (f" — {check.detail}" if check.detail else ""))
        print()
    print(
        f"Summary: PASS={report.summary.get('PASS', 0)} "
        f"FAIL={report.summary.get('FAIL', 0)} "
        f"MISSING={report.summary.get('MISSING', 0)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit MCP provider data flow across the stack.")
    parser.add_argument(
        "--output-dir",
        default=str(_REPO / "artifacts" / "audit"),
        help="Directory for mcp_audit_report.json and mcp_audit_report.md",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress console summary")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_audit()
    json_path, md_path = write_reports(report, Path(args.output_dir))
    if not args.quiet:
        print_console_summary(report)
        print(f"Wrote {json_path}")
        print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
