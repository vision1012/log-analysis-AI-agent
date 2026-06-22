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
