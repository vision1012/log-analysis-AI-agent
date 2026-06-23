#!/usr/bin/env python3
"""
Neo4j Investigation Graph completeness audit — read-only static analysis.

Verifies node labels, relationship types, constraints, indexes, write/read paths,
graph visualization, timeline, reports, and similar-incident coverage.

Does not modify runtime behavior or business logic.

Usage::

    python scripts/audit_neo4j_graph.py
    python scripts/audit_neo4j_graph.py --output-dir artifacts/audit
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

NODE_LABELS = (
    "Investigation",
    "JiraTicket",
    "PullRequest",
    "MergeRequest",
    "Commit",
    "Build",
    "Deployment",
    "MetricEvent",
    "AlertEvent",
    "TraceEvent",
    "PagerDutyIncident",
    "Runbook",
    "KnownIssue",
    "ArchitectureDocument",
    "Feedback",
    "RCACandidate",
)

RELATIONSHIP_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("pr_has_commit", "PullRequest", "HAS_COMMIT", "Commit"),
    ("commit_triggered_build", "Commit", "TRIGGERED_BUILD", "Build"),
    ("build_produced_deployment", "Build", "PRODUCED_DEPLOYMENT", "Deployment"),
    ("deployment_to_alert", "Deployment", "OBSERVED_METRIC→TRIGGERED_ALERT", "AlertEvent"),
    ("alert_to_incident", "AlertEvent", "ESCALATED_TO", "PagerDutyIncident"),
    ("service_to_runbook", "Service", "HAS_RUNBOOK", "Runbook"),
    ("alert_to_known_issue", "AlertEvent", "MATCHES_KNOWN_ISSUE", "KnownIssue"),
    ("investigation_to_feedback", "Investigation", "HAS_FEEDBACK", "Feedback"),
    ("feedback_to_rca_candidate", "Feedback", "TARGETS_CANDIDATE", "RCACandidate"),
)

NODE_CHECK_IDS = (
    "constraints",
    "indexes",
    "write_path",
    "read_path",
    "graph_visualization",
    "timeline",
    "reports",
    "similar_incidents",
)

REL_CHECK_IDS = (
    "write_path",
    "read_path",
    "graph_visualization",
    "timeline",
    "reports",
    "similar_incidents",
)

NODE_CHECK_LABELS: dict[str, str] = {
    "constraints": "Constraints",
    "indexes": "Indexes",
    "write_path": "Write Path",
    "read_path": "Read Path",
    "graph_visualization": "Graph Visualization",
    "timeline": "Timeline",
    "reports": "Reports",
    "similar_incidents": "Similar Incidents",
}

REL_CHECK_LABELS: dict[str, str] = {
    "write_path": "Write Path",
    "read_path": "Read Path",
    "graph_visualization": "Graph Visualization",
    "timeline": "Timeline",
    "reports": "Reports",
    "similar_incidents": "Similar Incidents",
}


@dataclass
class AuditCheckResult:
    check_id: str
    label: str
    status: AuditStatus
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class NodeAuditResult:
    label: str
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
class RelationshipAuditResult:
    rel_id: str
    source_label: str
    rel_type: str
    target_label: str
    checks: list[AuditCheckResult] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f"{self.source_label} -[:{self.rel_type}]-> {self.target_label}"

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
class Neo4jAuditReport:
    generated_at: str
    repo_root: str
    nodes: list[NodeAuditResult] = field(default_factory=list)
    relationships: list[RelationshipAuditResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "summary": self.summary,
            "nodes": [
                {
                    "label": node.label,
                    "pass_count": node.pass_count,
                    "fail_count": node.fail_count,
                    "missing_count": node.missing_count,
                    "checks": [asdict(check) for check in node.checks],
                }
                for node in self.nodes
            ],
            "relationships": [
                {
                    "rel_id": rel.rel_id,
                    "source_label": rel.source_label,
                    "rel_type": rel.rel_type,
                    "target_label": rel.target_label,
                    "display_name": rel.display_name,
                    "pass_count": rel.pass_count,
                    "fail_count": rel.fail_count,
                    "missing_count": rel.missing_count,
                    "checks": [asdict(check) for check in rel.checks],
                }
                for rel in self.relationships
            ],
        }


def _read_text(relative_path: str) -> str:
    path = _REPO / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _files_exist(relative_paths: list[str]) -> list[str]:
    return [rel for rel in relative_paths if (_REPO / rel).is_file()]


def _any_contains(files: list[str], patterns: list[str]) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in files:
        text = _read_text(rel)
        if not text:
            continue
        for pattern in patterns:
            if pattern in text:
                evidence.append(f"{rel}: {pattern}")
    return bool(evidence), evidence


def _all_files_contain(files: list[str], patterns: list[str]) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for rel in files:
        text = _read_text(rel)
        if not text:
            return False, evidence
        for pattern in patterns:
            if pattern not in text:
                return False, evidence
            evidence.append(f"{rel}: {pattern}")
    return True, evidence


def _check_constraints(label: str) -> AuditCheckResult:
    files = _files_exist(["graph/migrations_mcp.py", "graph/migrations.py"])
    for rel in files:
        text = _read_text(rel)
        if "CREATE CONSTRAINT" in text and label in text:
            return AuditCheckResult(
                "constraints",
                NODE_CHECK_LABELS["constraints"],
                "PASS",
                "uniqueness constraint declared",
                [f"{rel}: CREATE CONSTRAINT ... {label}"],
            )
    return AuditCheckResult(
        "constraints",
        NODE_CHECK_LABELS["constraints"],
        "MISSING",
        f"no uniqueness constraint found for {label}",
    )


def _check_indexes(label: str) -> AuditCheckResult:
    files = _files_exist(["graph/migrations_mcp.py", "graph/migrations.py"])
    for rel in files:
        text = _read_text(rel)
        if "CREATE INDEX" in text and label in text:
            return AuditCheckResult(
                "indexes",
                NODE_CHECK_LABELS["indexes"],
                "PASS",
                "index declared in migrations",
                [f"{rel}: CREATE INDEX ... {label}"],
            )
    return AuditCheckResult(
        "indexes",
        NODE_CHECK_LABELS["indexes"],
        "MISSING",
        f"no index declared for {label}",
    )


def _apply_rule_check(check_id: str, rule: dict[str, Any], *, labels: dict[str, str]) -> AuditCheckResult:
    label = labels[check_id]
    existing = _files_exist(rule.get("files", []))
    if not existing:
        return AuditCheckResult(check_id, label, "MISSING", "configured files not found")

    patterns_all = rule.get("patterns_all") or []
    patterns_any = rule.get("patterns_any") or []
    partial = rule.get("partial_detail", "")

    all_ok = True
    any_ok = True
    evidence: list[str] = []

    if patterns_all:
        all_ok, all_evidence = _all_files_contain(existing, patterns_all)
        evidence.extend(all_evidence)
    if patterns_any:
        any_ok, any_evidence = _any_contains(existing, patterns_any)
        evidence.extend(any_evidence)

    if patterns_all and patterns_any:
        primary_ok = all_ok and any_ok
    elif patterns_all:
        primary_ok = all_ok
    elif patterns_any:
        primary_ok = any_ok
    else:
        primary_ok = True

    evidence = list(dict.fromkeys(evidence))

    if primary_ok and not partial:
        return AuditCheckResult(check_id, label, "PASS", "integration references found", evidence)
    if primary_ok and partial:
        return AuditCheckResult(check_id, label, "FAIL", partial, evidence)
    if partial:
        return AuditCheckResult(check_id, label, "FAIL", partial)
    return AuditCheckResult(check_id, label, "MISSING", "no matching references found")


# Per-node audit rules: static codebase references only.
NODE_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "Investigation": {
        "write_path": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_investigation", "persist_investigation_context"],
        },
        "read_path": {
            "files": ["graph/graph_visualization_service.py", "graph/investigation_retriever.py"],
            "patterns_any": ["investigation_exists", "Investigation {id"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Investigation"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["Investigation {id", "investigation_created_at"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph", "graph_summary"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["MATCH (current:Investigation", "MATCH (other:Investigation"],
        },
    },
    "JiraTicket": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_jira_ticket", "link_investigation_jira_ticket"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py", "investigation/timeline_service.py"],
            "patterns_any": ["JiraTicket", "HAS_JIRA_TICKET"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"JiraTicket"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "JiraTicket"', "JIRA_CREATED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "graph/graph_visualization_service.py"],
            "patterns_any": ["get_investigation_graph", "JiraTicket"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py", "graph/investigation_retriever.py"],
            "patterns_any": ["HAS_JIRA_TICKET", "JiraTicket"],
        },
    },
    "PullRequest": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_pull_request", "link_pull_request_commit"],
        },
        "read_path": {
            "files": ["investigation/timeline_service.py", "graph/investigation_retriever.py"],
            "patterns_any": ["PullRequest", "MergeRequest"],
            "partial_detail": "no dedicated retriever method; reachable via graph traversal/timeline only",
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"PullRequest"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "PullRequest"', "PR_MERGED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["PullRequest"],
            "partial_detail": "not a scored shared-entity factor in similar incident traversal",
        },
    },
    "MergeRequest": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_merge_request", "MERGE (n:MergeRequest"],
        },
        "read_path": {
            "files": ["investigation/timeline_service.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["MergeRequest", "merge_requests"],
            "partial_detail": "no dedicated retriever method; timeline and persist path only",
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"MergeRequest"', "LABEL_ALIASES"],
            "partial_detail": "MergeRequest aliased to PullRequest; not a distinct visualization node type",
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "MergeRequest"', "SOURCE_GITLAB"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["MergeRequest"],
            "partial_detail": "not a scored shared-entity factor in similar incident traversal",
        },
    },
    "Commit": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_commit", "link_commit_build"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_recent_commits_for_service", ":Commit"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Commit"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "Commit"', "COMMIT_PUSHED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Commit": "commit_match"', "commit_match"],
        },
    },
    "Build": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_build", "link_build_deployment"],
        },
        "read_path": {
            "files": ["agents/investigation_context_loader.py", "investigation/timeline_service.py"],
            "patterns_any": [":Build", "BUILD_STARTED", "_fetch_builds"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Build"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "Build"', "BUILD_COMPLETED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["build_match", '"Build"'],
        },
    },
    "Deployment": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_deployment", "link_build_deployment"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_deployments", ":Deployment"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Deployment"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "Deployment"', "DEPLOYMENT_COMPLETED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Deployment": "deployment_match"', "deployment_match"],
        },
    },
    "MetricEvent": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_metric_event", "link_deployment_metric"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": [":MetricEvent", "OBSERVED_METRIC"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"MetricEvent"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "MetricEvent"', "METRIC_SPIKE"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["MetricEvent"],
            "partial_detail": "not a dedicated similar-incident shared-entity factor",
        },
    },
    "AlertEvent": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_alert_event", "link_metric_alert"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_alerts", ":AlertEvent"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"AlertEvent"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "AlertEvent"', "ALERT_TRIGGERED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"AlertEvent": "alert_match"', "alert_match"],
        },
    },
    "TraceEvent": {
        "write_path": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_trace_event", "trace_events"],
        },
        "read_path": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": [":TraceEvent", "TraceEvent"],
            "partial_detail": "no dedicated retriever method; timeline mapper only",
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"TraceEvent"'],
            "partial_detail": "TraceEvent not included in VISUALIZATION_NODE_TYPES",
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "TraceEvent"', "_events_from_trace"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "reporting/markdown_exporter.py"],
            "patterns_any": ["TraceEvent", "trace"],
            "partial_detail": "no dedicated TraceEvent section in investigation reports",
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["TraceEvent"],
            "partial_detail": "not a scored shared-entity factor in similar incident traversal",
        },
    },
    "PagerDutyIncident": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_pagerduty_incident", "link_alert_pagerduty_incident"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_incidents", ":PagerDutyIncident"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"PagerDutyIncident"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "PagerDutyIncident"', "INCIDENT_OPENED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["pagerduty_incident_match", "PagerDutyIncident"],
        },
    },
    "Runbook": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_runbook", "link_service_runbook"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_runbooks_for_service", ":Runbook"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Runbook"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "Runbook"', "RUNBOOK_MATCHED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "reporting/markdown_exporter.py"],
            "patterns_any": ["runbooks", "Runbooks"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"Runbook": "runbook_match"', "runbook_match"],
        },
    },
    "KnownIssue": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["upsert_known_issue", "link_alert_known_issue"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_known_issues_for_alert", ":KnownIssue"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"KnownIssue"'],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["KnownIssue"],
            "partial_detail": "no timeline event mapper for KnownIssue nodes",
        },
        "reports": {
            "files": ["reporting/report_builder.py", "agents/knowledge_agent.py"],
            "patterns_any": ["known_issues", "known issue"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ['"KnownIssue": "known_issue_match"', "known_issue_match"],
        },
    },
    "ArchitectureDocument": {
        "write_path": {
            "files": ["graph/investigation_writer.py", "graph/investigation_graph_service.py"],
            "patterns_any": ["upsert_architecture_document", "architecture_documents"],
        },
        "read_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["ArchitectureDocument", "link_service_architecture_document"],
            "partial_detail": "no dedicated retriever method; write/link path only",
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["HAS_ARCHITECTURE_DOC"],
            "partial_detail": "ArchitectureDocument not in VISUALIZATION_NODE_TYPES; edge type mapped only",
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["ArchitectureDocument"],
            "partial_detail": "no timeline event mapper for ArchitectureDocument nodes",
        },
        "reports": {
            "files": ["reporting/report_builder.py", "reporting/markdown_exporter.py"],
            "patterns_any": ["architecture", "ArchitectureDocument"],
            "partial_detail": "no dedicated ArchitectureDocument section in investigation reports",
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["ArchitectureDocument"],
            "partial_detail": "not a scored shared-entity factor in similar incident traversal",
        },
    },
    "Feedback": {
        "write_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["MERGE (f:Feedback", "HAS_FEEDBACK"],
        },
        "read_path": {
            "files": ["feedback/feedback_learning_service.py", "investigation/timeline_service.py"],
            "patterns_any": ["get_feedback_for_investigation", ":Feedback"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ['"Feedback"', "HAS_FEEDBACK"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ['label == "Feedback"', "FEEDBACK_SUBMITTED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "reporting/markdown_exporter.py"],
            "patterns_any": ["feedback_history", "Feedback History"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["historical_feedback", "get_feedback_by_investigation_ids"],
        },
    },
    "RCACandidate": {
        "write_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["MERGE (c:RCACandidate", "TARGETS_CANDIDATE"],
        },
        "read_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": [":RCACandidate", "candidate_id"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py", "investigation/timeline_service.py"],
            "patterns_any": ['"RCACandidate"', "TARGETS_CANDIDATE"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["RCACandidate"],
            "partial_detail": "RCACandidate explicitly excluded from timeline graph fetch",
        },
        "reports": {
            "files": ["reporting/report_builder.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["candidate_id", "RCACandidate"],
            "partial_detail": "RCA candidates surfaced via feedback history, not as graph nodes in reports",
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["RCACandidate", "root_cause_match"],
            "partial_detail": "root_cause_match uses file paths, not RCACandidate node traversal",
        },
    },
}

RELATIONSHIP_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "pr_has_commit": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_pull_request_commit", "HAS_COMMIT"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py", "investigation/timeline_service.py"],
            "patterns_any": ["HAS_COMMIT", "PullRequest"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["HAS_COMMIT"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["PR_MERGED", "COMMIT_PUSHED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["commit_match", "HAS_COMMIT"],
        },
    },
    "commit_triggered_build": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_commit_build", "TRIGGERED_BUILD"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["TRIGGERED_BUILD"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["TRIGGERED_BUILD"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["BUILD_STARTED", "BUILD_COMPLETED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["build_match", "TRIGGERED_BUILD"],
        },
    },
    "build_produced_deployment": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_build_deployment", "PRODUCED_DEPLOYMENT"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["PRODUCED_DEPLOYMENT", "get_related_deployments"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["PRODUCED_DEPLOYMENT"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["DEPLOYMENT_COMPLETED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["deployment_match", "PRODUCED_DEPLOYMENT"],
        },
    },
    "deployment_to_alert": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_all": ["link_deployment_metric", "link_metric_alert"],
            "patterns_any": ["OBSERVED_METRIC", "TRIGGERED_ALERT"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["OBSERVED_METRIC", "TRIGGERED_ALERT", "get_related_alerts"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["OBSERVED_METRIC", "TRIGGERED_ALERT"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["METRIC_SPIKE", "ALERT_TRIGGERED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["alert_match", "TRIGGERED_ALERT"],
            "partial_detail": "indirect two-hop chain Deployment→Metric→Alert; alert_match scores AlertEvent only",
        },
    },
    "alert_to_incident": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_alert_pagerduty_incident", "ESCALATED_TO"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_related_incidents", "ESCALATED_TO"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["ESCALATED_TO"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["INCIDENT_OPENED", "ALERT_TRIGGERED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["get_investigation_graph"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["pagerduty_incident_match", "ESCALATED_TO"],
        },
    },
    "service_to_runbook": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_service_runbook", "HAS_RUNBOOK"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_runbooks_for_service", "HAS_RUNBOOK"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["HAS_RUNBOOK"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["RUNBOOK_MATCHED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["runbooks"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py", "graph/investigation_retriever.py"],
            "patterns_any": ["runbook_match", "HAS_RUNBOOK"],
        },
    },
    "alert_to_known_issue": {
        "write_path": {
            "files": ["graph/investigation_writer.py"],
            "patterns_any": ["link_alert_known_issue", "MATCHES_KNOWN_ISSUE"],
        },
        "read_path": {
            "files": ["graph/investigation_retriever.py"],
            "patterns_any": ["get_known_issues_for_alert", "MATCHES_KNOWN_ISSUE"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["MATCHES_KNOWN_ISSUE"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["KnownIssue", "ALERT_TRIGGERED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "agents/knowledge_agent.py"],
            "patterns_any": ["known_issues"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py"],
            "patterns_any": ["known_issue_match", "MATCHES_KNOWN_ISSUE"],
        },
    },
    "investigation_to_feedback": {
        "write_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["HAS_FEEDBACK"],
        },
        "read_path": {
            "files": ["feedback/feedback_learning_service.py", "investigation/timeline_service.py"],
            "patterns_any": ["HAS_FEEDBACK", "get_feedback_for_investigation"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["HAS_FEEDBACK"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py"],
            "patterns_any": ["HAS_FEEDBACK", "FEEDBACK_SUBMITTED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py"],
            "patterns_any": ["feedback_history"],
        },
        "similar_incidents": {
            "files": ["graph/similar_incident_service.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["historical_feedback", "HAS_FEEDBACK"],
        },
    },
    "feedback_to_rca_candidate": {
        "write_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["TARGETS_CANDIDATE"],
        },
        "read_path": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["TARGETS_CANDIDATE", ":RCACandidate"],
        },
        "graph_visualization": {
            "files": ["graph/graph_visualization_service.py"],
            "patterns_any": ["TARGETS_CANDIDATE"],
        },
        "timeline": {
            "files": ["investigation/timeline_service.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["TARGETS_CANDIDATE", "FEEDBACK_SUBMITTED"],
        },
        "reports": {
            "files": ["reporting/report_builder.py", "feedback/feedback_learning_service.py"],
            "patterns_any": ["candidate_id", "TARGETS_CANDIDATE"],
        },
        "similar_incidents": {
            "files": ["feedback/feedback_learning_service.py"],
            "patterns_any": ["TARGETS_CANDIDATE"],
            "partial_detail": "similar incidents use file-path root_cause_match, not TARGETS_CANDIDATE traversal",
        },
    },
}


def _audit_node(label: str) -> NodeAuditResult:
    result = NodeAuditResult(label=label)
    result.checks.append(_check_constraints(label))
    result.checks.append(_check_indexes(label))

    rules = NODE_RULES.get(label, {})
    for check_id in NODE_CHECK_IDS:
        if check_id in {"constraints", "indexes"}:
            continue
        rule = rules.get(check_id)
        if not rule:
            result.checks.append(
                AuditCheckResult(check_id, NODE_CHECK_LABELS[check_id], "MISSING", "no audit rule configured")
            )
            continue
        result.checks.append(_apply_rule_check(check_id, rule, labels=NODE_CHECK_LABELS))
    return result


def _audit_relationship(rel_id: str, source: str, rel_type: str, target: str) -> RelationshipAuditResult:
    result = RelationshipAuditResult(
        rel_id=rel_id,
        source_label=source,
        rel_type=rel_type,
        target_label=target,
    )
    rules = RELATIONSHIP_RULES.get(rel_id, {})
    for check_id in REL_CHECK_IDS:
        rule = rules.get(check_id)
        if not rule:
            result.checks.append(
                AuditCheckResult(check_id, REL_CHECK_LABELS[check_id], "MISSING", "no audit rule configured")
            )
            continue
        result.checks.append(_apply_rule_check(check_id, rule, labels=REL_CHECK_LABELS))
    return result


def run_audit() -> Neo4jAuditReport:
    nodes = [_audit_node(label) for label in NODE_LABELS]
    relationships = [
        _audit_relationship(rel_id, source, rel_type, target)
        for rel_id, source, rel_type, target in RELATIONSHIP_SPECS
    ]
    summary = {"PASS": 0, "FAIL": 0, "MISSING": 0}
    for entity in (*nodes, *relationships):
        for check in entity.checks:
            summary[check.status] += 1
    return Neo4jAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO),
        nodes=nodes,
        relationships=relationships,
        summary=summary,
    )


def render_markdown(report: Neo4jAuditReport) -> str:
    lines = [
        "# Neo4j Investigation Graph Coverage Audit",
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
        "## Node Coverage",
        "",
    ]
    for node in report.nodes:
        lines.extend([f"### {node.label}", ""])
        for check in node.checks:
            line = f"[{check.status}] {check.label}"
            if check.detail:
                line += f" — {check.detail}"
            lines.append(line)
        lines.append("")

    lines.extend(["## Relationship Coverage", ""])
    for rel in report.relationships:
        lines.extend([f"### {rel.display_name}", ""])
        for check in rel.checks:
            line = f"[{check.status}] {check.label}"
            if check.detail:
                line += f" — {check.detail}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_reports(report: Neo4jAuditReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "neo4j_audit_report.json"
    md_path = output_dir / "neo4j_audit_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def print_console_summary(report: Neo4jAuditReport) -> None:
    print("=== Neo4j Investigation Graph Audit ===")
    print(f"generated_at={report.generated_at}")
    print()
    print("--- Nodes ---")
    for node in report.nodes:
        print(node.label)
        for check in node.checks:
            print(check.status, check.label + (f" — {check.detail}" if check.detail else ""))
        print()
    print("--- Relationships ---")
    for rel in report.relationships:
        print(rel.display_name)
        for check in rel.checks:
            print(check.status, check.label + (f" — {check.detail}" if check.detail else ""))
        print()
    print(
        f"Summary: PASS={report.summary.get('PASS', 0)} "
        f"FAIL={report.summary.get('FAIL', 0)} "
        f"MISSING={report.summary.get('MISSING', 0)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Neo4j investigation graph completeness.")
    parser.add_argument(
        "--output-dir",
        default=str(_REPO / "artifacts" / "audit"),
        help="Directory for neo4j_audit_report.md and neo4j_audit_report.json",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress console summary")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_audit()
    json_path, md_path = write_reports(report, Path(args.output_dir))
    if not args.quiet:
        print_console_summary(report)
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
