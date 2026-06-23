"""Unit tests for GraphRAG context completeness audit script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "audit_graphrag_context.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_graphrag_context", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_audit_covers_providers_and_contexts() -> None:
    mod = _load_module()
    report = mod.run_audit()
    provider_ids = {item.item_id for item in report.providers}
    context_ids = {item.item_id for item in report.contexts}
    assert provider_ids == set(mod.PROVIDER_ITEMS)
    assert context_ids == set(mod.CONTEXT_ITEMS)
    assert report.summary["total"] == len(mod.PROVIDER_ITEMS) + len(mod.CONTEXT_ITEMS)


def test_feedback_and_multi_agent_are_used() -> None:
    mod = _load_module()
    report = mod.run_audit()
    by_id = {item.item_id: item.status for item in report.contexts}
    assert by_id["feedback"] == "used"
    assert by_id["multi_agent_findings"] == "used"


def test_github_datadog_and_timeline_are_used() -> None:
    mod = _load_module()
    report = mod.run_audit()
    provider_status = {item.item_id: item.status for item in report.providers}
    context_status = {item.item_id: item.status for item in report.contexts}
    assert provider_status["github"] == "used"
    assert provider_status["datadog"] == "used"
    assert context_status["timeline"] == "used"
    assert context_status["confidence_information"] == "used"


def test_jira_is_available_but_unused_and_similar_incidents_used() -> None:
    mod = _load_module()
    report = mod.run_audit()
    provider_status = {item.item_id: item.status for item in report.providers}
    context_status = {item.item_id: item.status for item in report.contexts}
    assert provider_status["jira"] == "used"
    assert context_status["similar_incidents"] == "used"


def test_no_graphrag_audit_gaps() -> None:
    mod = _load_module()
    report = mod.run_audit()
    assert report.summary["missing"] == 0
    assert report.summary["available_but_unused"] == 0
    assert not report.missing
    assert not report.available_but_unused


def test_write_reports_creates_markdown(tmp_path) -> None:
    mod = _load_module()
    report = mod.run_audit()
    json_path, md_path = mod.write_reports(report, tmp_path)
    assert md_path.name == "graphrag_audit_report.md"
    text = md_path.read_text(encoding="utf-8")
    assert "## USED" in text
    assert "## AVAILABLE BUT UNUSED" in text
    assert "## MISSING" in text
    assert "## MCP Provider Detail" in text
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "used" in payload
    assert "available_but_unused" in payload
    assert "missing" in payload
    assert len(payload["providers"]) == len(mod.PROVIDER_ITEMS)
