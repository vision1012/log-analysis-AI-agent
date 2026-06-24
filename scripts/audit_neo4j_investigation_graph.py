#!/usr/bin/env python3
"""
Neo4j Investigation Graph completeness audit — read-only static analysis.

Verifies node labels, constraints, indexes, write/read paths, graph visualization,
timeline, reports, and similar-incident coverage across the investigation graph.

Does not modify runtime behavior or business logic.

Usage::

    python scripts/audit_neo4j_investigation_graph.py
    python scripts/audit_neo4j_investigation_graph.py --output-dir artifacts/audit
"""

from __future__ import annotations

import argparse
import json
import re
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
    "Commit",
    "PullRequest",
    "Build",
    "Deployment",
    "MetricEvent",
    "AlertEvent",
    "PagerDutyIncident",
    "Runbook",
    "KnownIssue",
    "Feedback",
)

CHECK_IDS = (
    "constraints",
    "indexes",
    "write_path",
    "read_path",
    "graph_visualization",
    "timeline",
    "reports",
    "similar_incidents",
)

CHECK_LABELS: dict[str, str] = {
    "constraints": "Constraints",
    "indexes": "Indexes",
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
class Neo4jAuditReport:
    generated_at: str
    repo_root: str
    nodes: list[NodeAuditResult] = field(default_factory=list)
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


def _constraint_patterns(label: str) -> list[str]:
    escaped = re.escape(label)
    return [
        f'"{label}"',
        f"({label})",
        f":{label}",
        f"FOR (n:{label})",
        f"FOR (c:{label})",
    ]


def _check_constraints(label: str) -> AuditCheckResult:
    files = _files_exist(["graph/migrations_mcp.py", "graph/migrations.py"])
    patterns = _constraint_patterns(label)
    if label == "Commit":
        patterns.extend(["constraint_mcp_commit_sha", "constraint_commit_sha"])
    ok, evidence = _any_contains(files, patterns)
    if ok and any("CREATE CONSTRAINT" in _read_text(rel) or "REQUIRE" in _read_text(rel) for rel in files):
        # Require an actual constraint declaration mentioning the label
        constraint_hits = [
            item
            for item in evidence
            if "CREATE CONSTRAINT" in _read_text(item.split(":")[0]) or True
        ]
        if constraint_hits or evidence:
            # Confirm at least one migrations file has CREATE CONSTRAINT + label
            for rel in files:
                text = _read_text(rel)
                if "CREATE CONSTRAINT" in text and label in text:
                    return AuditCheckResult(
                        "constraints",
                        CHECK_LABELS["constraints"],
                        "PASS",
                        "uniqueness constraint declared",
                        [f"{rel}: CREATE CONSTRAINT ... {label}"],
                    )
    return AuditCheckResult(
        "constraints",
        CHECK_LABELS["constraints"],
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
                CHECK_LABELS["indexes"],
                "PASS",
                "index declared in migrations",
                [f"{rel}: CREATE INDEX ... {label}"],
            )
    return AuditCheckResult(
        "indexes",
        CHECK_LABELS["indexes"],
        "MISSING",
        f"no index declared for {label}",
    )


def _pattern_check(
    check_id: str,
    *,
    files: list[str],
    patterns_any: list[str],
    partial_detail: str = "",
) -> AuditCheckResult:
    label = CHECK_LABELS[check_id]
    existing = _files_exist(files)
    if not existing:
        return AuditCheckResult(check_id, label, "MISSING", "configured files not found")
    ok, evidence = _any_contains(existing, patterns_any)
    if ok:
        return AuditCheckResult(check_id, label, "PASS", "integration references found", evidence)
    if partial_detail:
        return AuditCheckResult(check_id, label, "FAIL", partial_detail)
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
            "patterns_any": ["KnownIssue", "KNOWN_ISSUE_MATCHED", "_events_from_known_issue"],
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
}


def _audit_node(label: str) -> NodeAuditResult:
    result = NodeAuditResult(label=label)
    result.checks.append(_check_constraints(label))
    result.checks.append(_check_indexes(label))

    rules = NODE_RULES.get(label, {})
    for check_id in CHECK_IDS:
        if check_id in {"constraints", "indexes"}:
            continue
        rule = rules.get(check_id)
        if not rule:
            result.checks.append(
                AuditCheckResult(check_id, CHECK_LABELS[check_id], "MISSING", "no audit rule configured")
            )
            continue

        existing = _files_exist(rule.get("files", []))
        ok, evidence = _any_contains(existing, rule.get("patterns_any", []))
        partial = rule.get("partial_detail", "")

        if ok and not partial:
            result.checks.append(
                AuditCheckResult(
                    check_id,
                    CHECK_LABELS[check_id],
                    "PASS",
                    "integration references found",
                    evidence,
                )
            )
        elif ok and partial:
            result.checks.append(
                AuditCheckResult(check_id, CHECK_LABELS[check_id], "FAIL", partial, evidence)
            )
        elif partial:
            result.checks.append(AuditCheckResult(check_id, CHECK_LABELS[check_id], "FAIL", partial))
        else:
            result.checks.append(
                AuditCheckResult(check_id, CHECK_LABELS[check_id], "MISSING", "no matching references found")
            )
    return result


def run_audit() -> Neo4jAuditReport:
    nodes = [_audit_node(label) for label in NODE_LABELS]
    summary = {"PASS": 0, "FAIL": 0, "MISSING": 0}
    for node in nodes:
        for check in node.checks:
            summary[check.status] += 1
    return Neo4jAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO),
        nodes=nodes,
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
    for node in report.nodes:
        print(node.label)
        for check in node.checks:
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
