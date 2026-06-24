"""
MCP investigation graph migrations for Neo4j.

Creates uniqueness constraints and indexes for investigation-context node identities.
Idempotent (IF NOT EXISTS).

Usage:
    from graph.migrations_mcp import apply_mcp_migrations
    apply_mcp_migrations(uri, user, password)

    # Or from env:
    python -m graph.migrations_mcp
    python -m graph.migrations_mcp --report-dir artifacts/audit
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graph.neo4j_client import Neo4jClient

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Uniqueness constraints: (constraint_name, label, property)
# Recommended semantic keys (ticket_key, pr_id, mr_id, ...) mirror MERGE keys set in investigation_writer.
MCP_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("constraint_investigation_id", "Investigation", "id"),
    ("constraint_jira_ticket_ticket_key", "JiraTicket", "ticket_key"),
    ("constraint_pull_request_pr_id", "PullRequest", "pr_id"),
    ("constraint_merge_request_mr_id", "MergeRequest", "mr_id"),
    ("constraint_mcp_commit_sha", "Commit", "sha"),
    ("constraint_mcp_build_id", "Build", "id"),
    ("constraint_mcp_deployment_id", "Deployment", "id"),
    ("constraint_metric_event_metric_id", "MetricEvent", "metric_id"),
    ("constraint_trace_event_trace_id", "TraceEvent", "trace_id"),
    ("constraint_mcp_alert_id", "AlertEvent", "id"),
    ("constraint_pagerduty_incident_id", "PagerDutyIncident", "id"),
    ("constraint_runbook_id", "Runbook", "id"),
    ("constraint_known_issue_id", "KnownIssue", "id"),
    ("constraint_architecture_document_id", "ArchitectureDocument", "document_id"),
    ("constraint_feedback_id", "Feedback", "feedback_id"),
    ("constraint_rca_candidate_id", "RCACandidate", "candidate_id"),
)

# Non-constraint indexes: (index_name, label, property)
MCP_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("index_jira_ticket_ticket_key", "JiraTicket", "ticket_key"),
    ("index_jira_ticket_issue_key", "JiraTicket", "issue_key"),
    ("index_pull_request_pr_id", "PullRequest", "pr_id"),
    ("index_pull_request_number", "PullRequest", "number"),
    ("index_merge_request_mr_id", "MergeRequest", "mr_id"),
    ("index_merge_request_iid", "MergeRequest", "iid"),
    ("index_metric_event_metric_id", "MetricEvent", "metric_id"),
    ("index_metric_event_timestamp", "MetricEvent", "timestamp"),
    ("index_metric_event_service", "MetricEvent", "service"),
    ("index_trace_event_trace_id", "TraceEvent", "trace_id"),
    ("index_trace_event_timestamp", "TraceEvent", "timestamp"),
    ("index_trace_event_service", "TraceEvent", "service"),
    ("index_architecture_document_document_id", "ArchitectureDocument", "document_id"),
    ("index_architecture_document_service_name", "ArchitectureDocument", "service_name"),
    ("index_architecture_document_updated_at", "ArchitectureDocument", "updated_at"),
    ("index_deployment_timestamp", "Deployment", "timestamp"),
    ("index_commit_timestamp", "Commit", "timestamp"),
)


@dataclass
class SchemaChange:
    kind: str
    name: str
    label: str
    property: str
    cypher: str


@dataclass
class MCPMigrationReport:
    generated_at: str
    repo_root: str
    constraints: list[SchemaChange]
    indexes: list[SchemaChange]
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "applied": self.applied,
            "summary": {
                "constraint_count": len(self.constraints),
                "index_count": len(self.indexes),
                "labels_with_constraints": sorted({item.label for item in self.constraints}),
                "labels_with_indexes": sorted({item.label for item in self.indexes}),
            },
            "constraints": [asdict(item) for item in self.constraints],
            "indexes": [asdict(item) for item in self.indexes],
        }


def build_migration_report(*, applied: bool = False) -> MCPMigrationReport:
    """Build a static report describing declared MCP schema migrations."""
    constraints = [
        SchemaChange(
            kind="constraint",
            name=name,
            label=label,
            property=prop,
            cypher=(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            ),
        )
        for name, label, prop in MCP_CONSTRAINTS
    ]
    indexes = [
        SchemaChange(
            kind="index",
            name=name,
            label=label,
            property=prop,
            cypher=(
                f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            ),
        )
        for name, label, prop in MCP_INDEXES
    ]
    return MCPMigrationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO_ROOT),
        constraints=constraints,
        indexes=indexes,
        applied=applied,
    )


def render_migration_report_markdown(report: MCPMigrationReport) -> str:
    lines = [
        "# MCP Neo4j Migration Report",
        "",
        f"**Generated:** {report.generated_at}",
        f"**Repository:** `{report.repo_root}`",
        f"**Applied to database:** {report.applied}",
        "",
        "## Summary",
        "",
        f"- Constraints: {len(report.constraints)}",
        f"- Indexes: {len(report.indexes)}",
        "",
        "## Constraints",
        "",
    ]
    for item in report.constraints:
        lines.append(f"- `{item.name}` — **{item.label}**(`{item.property}`)")
    lines.extend(["", "## Indexes", ""])
    for item in report.indexes:
        lines.append(f"- `{item.name}` — **{item.label}**(`{item.property}`)")
    lines.extend(
        [
            "",
            "## Path Verification",
            "",
            "- **Write path:** `graph/investigation_writer.py` MERGE keys align with constraint properties "
            "(semantic aliases: ticket_key, pr_id, mr_id, metric_id, trace_id, document_id)",
            "- **Read path:** `graph/investigation_retriever.py` and timeline/graph services query by `id` / `issue_key`",
            "- **Retrieval path:** `graph/similar_incident_service.py` traverses investigation subgraph nodes",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def write_migration_report(
    report: MCPMigrationReport,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write JSON and Markdown migration reports."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "neo4j_migration_report.json"
    md_path = out / "neo4j_migration_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_migration_report_markdown(report), encoding="utf-8")
    return json_path, md_path


def apply_mcp_migrations(
    uri: str,
    user: str,
    password: str,
    *,
    report_dir: str | Path | None = None,
) -> MCPMigrationReport:
    """Apply MCP investigation graph constraints and indexes."""
    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        _log("Applying MCP investigation graph migrations...")
        _apply_constraints(client)
        _apply_indexes(client)
        _log("MCP migrations complete.")
        report = build_migration_report(applied=True)
    finally:
        client.close()

    if report_dir is not None:
        json_path, md_path = write_migration_report(report, report_dir)
        _log(f"Wrote {json_path}")
        _log(f"Wrote {md_path}")
    return report


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _apply_constraints(client: "Neo4jClient") -> None:
    for name, label, prop in MCP_CONSTRAINTS:
        q = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        _log(f"  Constraint: {label}({prop})")
        client.execute_write(q)


def _apply_indexes(client: "Neo4jClient") -> None:
    for name, label, prop in MCP_INDEXES:
        q = f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
        _log(f"  Index: {label}({prop})")
        client.execute_write(q)


def _build_cli_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Apply MCP Neo4j investigation graph migrations.")
    parser.add_argument(
        "--report-dir",
        default=str(_REPO_ROOT / "artifacts" / "audit"),
        help="Directory for neo4j_migration_report.json and .md",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Write migration report without connecting to Neo4j",
    )
    return parser


if __name__ == "__main__":
    args = _build_cli_parser().parse_args()
    if args.report_only:
        report = build_migration_report(applied=False)
        write_migration_report(report, args.report_dir)
        _log("Migration report written (report-only mode).")
        raise SystemExit(0)

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        raise SystemExit(1)
    apply_mcp_migrations(uri, user, password, report_dir=args.report_dir)
