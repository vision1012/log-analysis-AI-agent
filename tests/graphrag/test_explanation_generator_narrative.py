"""Tests for explanation generator narrative integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from graphrag.explanation_generator import generate_explanation


class _MockGraphClient:
    def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "MATCH (a:Anomaly {id:" in query and "RCA_ATTRIBUTED" not in query:
            return [{"anomaly_id": "an-1", "trace_ref": "trace-1", "service_ref": "auth-service"}]
        if "RCA_ATTRIBUTED" in query and "LIMIT 1" in query:
            return [{"run_id": "run-1", "ts": "2024-01-01T12:00:00Z"}]
        if "RCA_ATTRIBUTED" in query:
            return [
                {
                    "run_id": "run-1",
                    "status": "candidate",
                    "confidence": 0.8,
                    "evidence_ref": "bundle-1",
                    "file_id": "file-1",
                    "path": "/srv/auth/handler.py",
                }
            ]
        return []


class _MockEvidenceStore:
    def get_bundle(self, evidence_ref: str) -> dict[str, Any] | None:
        return {
            "signal_scores": {"last_touch_recency": 0.5},
            "raw_score": 0.8,
            "capped_score": 0.8,
            "path": "/srv/auth/handler.py",
            "last_touch_commit_sha": "abc123",
            "deployment_id": "dep-1",
            "prior_count": 0,
            "confidence_assessment": {
                "candidate": "/srv/auth/handler.py",
                "confidence": 0.88,
                "confidence_level": "high",
                "supporting_factors": ["Strong graph evidence (stack trace, recency, resolution)"],
                "contradicting_factors": [],
                "evidence_breakdown": {"strong_graph_evidence": 0.1},
            },
        }


@patch("graphrag.explanation_generator.validate_or_repair_output")
@patch("graphrag.context_packer.InvestigationGraphRetriever")
def test_generate_explanation_includes_narrative_fields(mock_retriever_cls, mock_validate) -> None:
    mock_retriever_cls.return_value = MagicMock()
    mock_retriever_cls.return_value.get_related_deployments.return_value = []
    mock_retriever_cls.return_value.get_related_alerts.return_value = []
    mock_retriever_cls.return_value.get_related_incidents.return_value = []
    mock_retriever_cls.return_value.get_recent_commits_for_service.return_value = []
    mock_retriever_cls.return_value.get_runbooks_for_service.return_value = []
    mock_retriever_cls.return_value.get_previous_similar_investigations.return_value = []

    mock_validate.side_effect = lambda output, **kwargs: output

    llm = MagicMock()
    llm.config = MagicMock(provider="ollama", model="test")
    llm.generate.return_value = {
        "explanation_summary": "Assistive summary",
        "evidence_highlights": ["highlight"],
        "confidence_alignment_note": "Deterministic ranking is authoritative.",
        "optional_patch_direction": "",
        "limitations": "",
    }

    client = _MockGraphClient()
    client._driver = object()
    out = generate_explanation(
        "an-1",
        graph_client=client,  # type: ignore[arg-type]
        evidence_store=_MockEvidenceStore(),
        llm_client=llm,
        service_name="auth-service",
    )

    assert out["primary_candidate"]["file_id"] == "file-1"
    assert "timeline" in out
    assert "causal_chain" in out
    assert "investigation_summary" in out
    assert "investigation_narrative" in out
    assert out.get("confidence_assessment", {}).get("confidence_level") == "high"
    assert "confidence_reasoning" in out
    assert "0.88" in out["confidence_reasoning"]
