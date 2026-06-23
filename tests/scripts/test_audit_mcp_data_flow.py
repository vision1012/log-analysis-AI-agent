"""Unit tests for MCP data-flow audit script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "audit_mcp_data_flow.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_mcp_data_flow", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_audit_generates_all_providers() -> None:
    mod = _load_module()
    report = mod.run_audit()
    assert len(report.providers) == 8
    names = {provider.provider for provider in report.providers}
    assert names == set(mod.PROVIDERS)


def test_each_provider_has_thirteen_checks() -> None:
    mod = _load_module()
    report = mod.run_audit()
    for provider in report.providers:
        assert len(provider.checks) == len(mod.CHECK_IDS)
        check_ids = {check.check_id for check in provider.checks}
        assert check_ids == set(mod.CHECK_IDS)


def test_registry_and_health_pass_for_all_providers() -> None:
    mod = _load_module()
    report = mod.run_audit()
    for provider in report.providers:
        registry = next(check for check in provider.checks if check.check_id == "registry")
        health = next(check for check in provider.checks if check.check_id == "health_check")
        assert registry.status == "PASS", provider.provider
        assert health.status == "PASS", provider.provider


def test_write_reports_creates_json_and_markdown(tmp_path) -> None:
    mod = _load_module()
    report = mod.run_audit()
    json_path, md_path = mod.write_reports(report, tmp_path)
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["PASS"] > 0
    assert "MCP End-to-End Architecture Audit" in md_path.read_text(encoding="utf-8")


def test_github_similar_incidents_passes() -> None:
    mod = _load_module()
    github = next(provider for provider in mod.run_audit().providers if provider.provider == "github")
    similar = next(check for check in github.checks if check.check_id == "similar_incidents")
    assert similar.status == "PASS"


def test_kubernetes_similar_incidents_passes() -> None:
    mod = _load_module()
    kubernetes = next(provider for provider in mod.run_audit().providers if provider.provider == "kubernetes")
    similar = next(check for check in kubernetes.checks if check.check_id == "similar_incidents")
    assert similar.status == "PASS"


def test_mcp_audit_has_no_missing_checks() -> None:
    mod = _load_module()
    report = mod.run_audit()
    assert report.summary["MISSING"] == 0
    assert report.summary["PASS"] == 104
