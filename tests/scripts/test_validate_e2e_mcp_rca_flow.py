"""Unit tests for MCP RCA E2E validation helpers (no live API)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "validate_e2e_mcp_rca_flow.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_e2e_mcp_rca_flow", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_confidence_from_candidate_assessment() -> None:
    mod = _load_module()
    payload = {
        "rca": {
            "rca_result": {
                "candidate_root_causes": [
                    {
                        "path": "/srv/auth/handler.py",
                        "confidence_assessment": {
                            "candidate": "/srv/auth/handler.py",
                            "confidence": 0.88,
                            "confidence_level": "high",
                            "supporting_factors": ["Strong graph evidence"],
                            "contradicting_factors": [],
                        },
                    }
                ]
            }
        }
    }
    assessments = mod._extract_confidence_assessments(payload)
    assert len(assessments) == 1
    assert assessments[0]["confidence_level"] == "high"


def test_extract_confidence_from_top_level_list() -> None:
    mod = _load_module()
    payload = {"confidence_assessments": [{"confidence": 0.9, "confidence_level": "high"}]}
    assert len(mod._extract_confidence_assessments(payload)) == 1


def test_mock_ticket_shape() -> None:
    mod = _load_module()
    ticket = mod._mock_ticket("MOCK-1", "auth-service")
    assert ticket["ticket_key"] == "MOCK-1"
    assert "auth-service" in ticket["summary"]


def test_mock_coverage_context_expectations() -> None:
    mod = _load_module()
    coverage = mod._mock_coverage_context()
    assert coverage.get("coverage_level")
    assert "jira" in coverage.get("available_sources", [])
    assert "github" in coverage.get("available_sources", [])
    assert "datadog" in coverage.get("missing_sources", [])


def test_validate_coverage_suite_mock_expectations() -> None:
    mod = _load_module()
    run = mod.ValidationRun(mode="mock")
    coverage = mod._mock_coverage_context()
    mod._validate_coverage_suite(
        run,
        coverage,
        contribution_expectations=mod.MOCK_COVERAGE_EXPECTATIONS,
    )
    names = [check.name for check in run.checks]
    assert "Coverage generated" in names
    assert "Jira contributed" in names
    assert "GitHub contributed" in names
    assert "Datadog missing" in names
    assert not run.failed()


def test_validate_confidence_limitations_pass_and_fail() -> None:
    mod = _load_module()
    run_pass = mod.ValidationRun(mode="mock")
    mod._validate_confidence_limitations(
        run_pass,
        [{"confidence_limitations": ["Missing Jenkins", "Missing Datadog"]}],
    )
    assert any(c.name == "Confidence limitations generated" and c.status == "PASS" for c in run_pass.checks)

    run_fail = mod.ValidationRun(mode="mock")
    mod._validate_confidence_limitations(run_fail, [{"confidence": 0.5}])
    assert any(c.name == "Confidence limitations generated" and c.status == "FAIL" for c in run_fail.checks)


def test_extract_evidence_coverage_from_preview_payload() -> None:
    mod = _load_module()
    payload = {
        "evidence_coverage": {
            "coverage_score": 0.5,
            "coverage_level": "good",
            "available_sources": ["jira"],
            "missing_sources": ["datadog"],
        }
    }
    coverage = mod._extract_evidence_coverage(payload)
    assert coverage["coverage_level"] == "good"
    assert coverage["available_sources"] == ["jira"]


def test_workspace_has_provider_enabled_only() -> None:
    mod = _load_module()
    connections = [
        {"provider": "jira", "is_enabled": True},
        {"provider": "github", "is_enabled": False},
    ]
    assert mod._workspace_has_provider(connections, "jira") is True
    assert mod._workspace_has_provider(connections, "github") is False
    assert mod._workspace_has_provider(connections, "datadog") is False


def test_list_workspace_connections_without_postgres(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert mod._list_workspace_connections("team-a") == []


def test_postgres_configured_reads_env(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert mod._postgres_configured() is False
    monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost/test")
    assert mod._postgres_configured() is True


def test_build_parser_includes_db_live_mode() -> None:
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(
        ["--mode", "db-live", "--workspace-id", "team-a", "--ticket-key", "PROJ-1"]
    )
    assert args.mode == "db-live"
    assert args.workspace_id == "team-a"
    assert args.ticket_key == "PROJ-1"


def test_run_db_live_validation_requires_workspace_id(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost/test")
    args = mod.build_parser().parse_args(["--mode", "db-live", "--workspace-id", ""])
    assert mod.run_db_live_validation(args) == 1


def test_run_db_live_validation_skips_without_postgres(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    args = mod.build_parser().parse_args(
        ["--mode", "db-live", "--workspace-id", "team-a", "--ticket-key", "PROJ-1"]
    )
    assert mod.run_db_live_validation(args) == 0


def test_run_validation_delegates_db_live(monkeypatch) -> None:
    mod = _load_module()
    called: list[str] = []

    def fake_db_live(args):
        called.append(args.workspace_id)
        return 0

    monkeypatch.setattr(mod, "run_db_live_validation", fake_db_live)
    args = mod.build_parser().parse_args(
        ["--mode", "db-live", "--workspace-id", "ws-123"]
    )
    assert mod.run_validation(args) == 0
    assert called == ["ws-123"]
