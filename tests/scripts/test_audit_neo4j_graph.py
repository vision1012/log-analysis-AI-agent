"""Unit tests for Neo4j graph audit script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "audit_neo4j_graph.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_neo4j_graph", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_audit_covers_all_node_labels() -> None:
    mod = _load_module()
    report = mod.run_audit()
    labels = {node.label for node in report.nodes}
    assert labels == set(mod.NODE_LABELS)
    for node in report.nodes:
        assert len(node.checks) == len(mod.NODE_CHECK_IDS)


def test_run_audit_covers_all_relationships() -> None:
    mod = _load_module()
    report = mod.run_audit()
    rel_ids = {rel.rel_id for rel in report.relationships}
    expected = {spec[0] for spec in mod.RELATIONSHIP_SPECS}
    assert rel_ids == expected
    for rel in report.relationships:
        assert len(rel.checks) == len(mod.REL_CHECK_IDS)


def test_investigation_core_paths_pass() -> None:
    mod = _load_module()
    investigation = next(node for node in mod.run_audit().nodes if node.label == "Investigation")
    statuses = {check.check_id: check.status for check in investigation.checks}
    assert statuses["write_path"] == "PASS"
    assert statuses["read_path"] == "PASS"
    assert statuses["graph_visualization"] == "PASS"
    assert statuses["constraints"] == "PASS"


def test_write_reports_creates_markdown_and_json(tmp_path) -> None:
    mod = _load_module()
    report = mod.run_audit()
    json_path, md_path = mod.write_reports(report, tmp_path)
    assert md_path.name == "neo4j_audit_report.md"
    assert json_path.name == "neo4j_audit_report.json"
    assert "Neo4j Investigation Graph Coverage Audit" in md_path.read_text(encoding="utf-8")
    assert "## Relationship Coverage" in md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["PASS"] > 0
    assert len(payload["relationships"]) == len(mod.RELATIONSHIP_SPECS)


def test_pr_has_commit_relationship_write_path_passes() -> None:
    mod = _load_module()
    rel = next(r for r in mod.run_audit().relationships if r.rel_id == "pr_has_commit")
    write = next(check for check in rel.checks if check.check_id == "write_path")
    assert write.status == "PASS"
