"""Tests for MCP Neo4j migrations."""

from __future__ import annotations

import json
from pathlib import Path

from graph.migrations_mcp import (
    MCP_CONSTRAINTS,
    MCP_INDEXES,
    apply_mcp_migrations,
    build_migration_report,
    write_migration_report,
)


class _MockNeo4jClient:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def execute_write(self, query: str, parameters: dict | None = None) -> None:
        self.writes.append(query)


def test_schema_includes_gap_node_labels() -> None:
    labels = {label for _, label, _ in MCP_CONSTRAINTS}
    for label in (
        "JiraTicket",
        "PullRequest",
        "MergeRequest",
        "MetricEvent",
        "TraceEvent",
        "ArchitectureDocument",
    ):
        assert label in labels

    indexed_labels = {label for _, label, _ in MCP_INDEXES}
    for label in (
        "JiraTicket",
        "PullRequest",
        "MergeRequest",
        "MetricEvent",
        "TraceEvent",
        "ArchitectureDocument",
    ):
        assert label in indexed_labels


def test_apply_mcp_migrations_is_idempotent() -> None:
    from graph import migrations_mcp

    client = _MockNeo4jClient()
    migrations_mcp._apply_constraints(client)  # type: ignore[arg-type]
    migrations_mcp._apply_indexes(client)  # type: ignore[arg-type]

    assert all("IF NOT EXISTS" in query for query in client.writes)
    assert any("JiraTicket" in query and "issue_key" in query for query in client.writes)
    assert any("CREATE INDEX" in query and "MetricEvent" in query for query in client.writes)
    assert len(client.writes) == len(MCP_CONSTRAINTS) + len(MCP_INDEXES)


def test_apply_mcp_migrations_with_mock_client(monkeypatch, tmp_path: Path) -> None:
    client = _MockNeo4jClient()

    class _Factory:
        def __init__(self, uri: str, user: str, password: str) -> None:
            self.uri = uri

        def connect(self) -> None:
            return None

        def close(self) -> None:
            return None

        def execute_write(self, query: str, parameters: dict | None = None) -> None:
            client.execute_write(query, parameters)

    monkeypatch.setattr("graph.neo4j_client.Neo4jClient", _Factory)
    report = apply_mcp_migrations("bolt://test", "neo4j", "secret", report_dir=tmp_path)
    assert report.applied is True
    assert len(client.writes) == len(MCP_CONSTRAINTS) + len(MCP_INDEXES)
    json_path, md_path = tmp_path / "neo4j_migration_report.json", tmp_path / "neo4j_migration_report.md"
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["constraint_count"] == len(MCP_CONSTRAINTS)
    assert "ArchitectureDocument" in payload["summary"]["labels_with_constraints"]


def test_write_migration_report(tmp_path: Path) -> None:
    report = build_migration_report(applied=False)
    json_path, md_path = write_migration_report(report, tmp_path)
    assert json_path.name == "neo4j_migration_report.json"
    assert "MCP Neo4j Migration Report" in md_path.read_text(encoding="utf-8")
