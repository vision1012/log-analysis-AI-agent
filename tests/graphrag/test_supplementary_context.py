"""Tests for GraphRAG supplementary context packing and summarization."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from feedback.feedback_models import FeedbackRecord
from graphrag.context_packer import pack_context
from graphrag.evidence_summarizer import summarize_evidence
from graphrag.prompt_builder import build_minimal_deterministic_prompt
from mcp.schemas.jira_models import McpTicketContext


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
            "weights_used": {},
            "raw_score": 0.8,
            "capped_score": 0.8,
            "path": "/srv/auth/handler.py",
        }


class _UnifiedContext:
    ticket_key = "OPS-42"
    ticket_context = McpTicketContext(
        issue_key="OPS-42",
        summary="Auth outage",
        description="Users cannot log in",
        priority="P1",
        status="In Progress",
        labels=["auth", "sev1"],
    )


@patch("graphrag.context_packer._resolve_multi_agent_report")
@patch("graphrag.context_packer._pack_similar_incident_context")
@patch("graphrag.context_packer._pack_feedback_context")
@patch("graphrag.context_packer._pack_investigation_retrieval_context")
def test_pack_context_includes_supplementary_blocks(
    mock_investigation_ctx,
    mock_feedback_ctx,
    mock_similar_ctx,
    mock_multi_agent,
) -> None:
    mock_investigation_ctx.return_value = {"previous_investigations": []}
    mock_feedback_ctx.return_value = {
        "confirmed_rcas": [{"candidate_id": "c1", "feedback_type": "CONFIRMED"}],
        "rejected_rcas": [],
        "overridden_rcas": [],
    }
    mock_similar_ctx.return_value = {
        "previous_investigation_summaries": [{"investigation_id": "inv-old"}],
        "historical_feedback": [],
        "historical_root_causes": [{"investigation_id": "inv-old", "root_cause": "/srv/a.py"}],
        "historical_remediation_actions": [
            {"investigation_id": "inv-old", "action": "Rollback deployment", "source": "resolution_summary"}
        ],
    }
    mock_multi_agent.return_value = {
        "timeline_findings": {"summary": "Timeline signal", "confidence": 0.7},
        "deployment_findings": {},
        "infrastructure_findings": {},
        "incident_findings": {},
        "knowledge_findings": {},
        "rca_findings": {},
        "final_summary": "Agents agree on deployment correlation.",
    }

    client = _MockGraphClient()
    client._driver = object()
    pack = pack_context(
        "an-1",
        graph_client=client,  # type: ignore[arg-type]
        evidence_store=_MockEvidenceStore(),
        investigation_id="inv-1",
        unified_investigation_context=_UnifiedContext(),
    )

    assert pack["jira_ticket_context"]["summary"] == "Auth outage"
    assert pack["jira_ticket_context"]["priority"] == "P1"
    assert pack["jira_ticket_context"]["status"] == "In Progress"
    assert pack["feedback_context"]["confirmed_rcas"]
    assert pack["similar_incident_context"]["historical_root_causes"]
    assert pack["similar_incident_context"]["historical_remediation_actions"]
    assert pack["multi_agent_findings"]["final_summary"]


@patch("graphrag.context_packer._resolve_multi_agent_report")
@patch("graphrag.context_packer._pack_similar_incident_context")
@patch("graphrag.context_packer._pack_feedback_context")
@patch("graphrag.context_packer._pack_investigation_retrieval_context")
def test_summarize_and_prompt_include_historical_context(
    mock_investigation_ctx,
    mock_feedback_ctx,
    mock_similar_ctx,
    mock_multi_agent,
) -> None:
    mock_investigation_ctx.return_value = {"previous_investigations": []}
    mock_feedback_ctx.return_value = {"confirmed_rcas": [], "rejected_rcas": [], "overridden_rcas": []}
    mock_similar_ctx.return_value = {
        "previous_investigation_summaries": [],
        "historical_feedback": [],
        "historical_root_causes": [],
    }
    mock_multi_agent.return_value = {
        "timeline_findings": {},
        "deployment_findings": {},
        "infrastructure_findings": {},
        "incident_findings": {},
        "knowledge_findings": {},
        "rca_findings": {},
        "final_summary": "",
    }
    context_pack = {
        "anomaly_id": "an-1",
        "candidates": [
            {
                "rank": 1,
                "file_id": "file-1",
                "path": "/srv/auth/handler.py",
                "confidence": 0.8,
                "evidence_ref": "bundle-1",
                "signal_summary": [],
                "commit_deployment_evidence": {},
                "historical_recurrence_evidence": {},
            }
        ],
        "jira_ticket_context": {
            "issue_key": "OPS-42",
            "summary": "Auth outage",
            "description": "Users cannot log in",
            "priority": "P1",
            "status": "In Progress",
            "labels": ["auth"],
        },
        "feedback_context": {
            "confirmed_rcas": [
                FeedbackRecord(
                    feedback_id="fb-1",
                    investigation_id="inv-1",
                    candidate_id="cand-1",
                    feedback_type="CONFIRMED",
                    comments="Looks right",
                    user_id="u1",
                    created_at="2024-01-01T00:00:00Z",
                ).model_dump()
            ],
            "rejected_rcas": [],
            "overridden_rcas": [],
        },
        "similar_incident_context": {
            "previous_investigation_summaries": [
                {
                    "investigation_id": "inv-old",
                    "similarity_score": 0.8,
                    "resolution_summary": "Rollback fixed outage",
                }
            ],
            "historical_feedback": [],
            "historical_root_causes": [
                {"investigation_id": "inv-old", "root_cause": "/srv/auth/handler.py"}
            ],
            "historical_remediation_actions": [
                {"investigation_id": "inv-old", "action": "Rollback fixed outage", "source": "resolution_summary"}
            ],
        },
        "multi_agent_findings": {
            "timeline_findings": {"summary": "Deploy preceded alert", "confidence": 0.8},
            "deployment_findings": {},
            "infrastructure_findings": {},
            "incident_findings": {},
            "knowledge_findings": {},
            "rca_findings": {},
            "final_summary": "Deployment agent flagged recent release.",
        },
    }

    bullets = summarize_evidence(context_pack)
    categories = {bullet["category"] for bullet in bullets}
    assert "jira" in categories
    assert "feedback" in categories
    assert "similar_incident" in categories
    assert "multi_agent" in categories

    prompt = build_minimal_deterministic_prompt(context_pack, bullets)
    assert "Historical Feedback" in prompt["user"]
    assert "Historical Incidents" in prompt["user"]
    assert "Multi-Agent Findings" in prompt["user"]
    assert "Ticket Context" in prompt["user"]
    assert "Agent Findings" in prompt["user"]
    assert "ticket_context" in prompt["user"] or "jira_ticket_context" in prompt["user"]
    assert "## INCIDENT CONTEXT" in prompt["user"]
    assert "## SELECTED RCA CANDIDATE" in prompt["user"]
    assert "## CONFIDENCE" in prompt["user"]
    assert "## SUPPORTING SIGNALS" in prompt["user"]
    assert "## STACK-TRACE EVIDENCE" in prompt["user"]
    assert "## LOG EVIDENCE" in prompt["user"]
    assert "## DEPLOYMENT OR COMMIT CONTEXT" in prompt["user"]
    assert "## GRAPH CONTEXT" in prompt["user"]
    assert "## MISSING EVIDENCE" in prompt["user"]
    assert "180-300" in prompt["system"]
    assert "must not replace, rerank, or contradict" in prompt["system"].lower()


def test_narrative_includes_supplementary_context() -> None:
    from graphrag.narrative_generator import generate_investigation_narrative

    narrative = generate_investigation_narrative(
        {"candidates": [{"path": "/srv/auth/handler.py", "confidence": 0.8}]},
        supplementary_context={
            "jira_ticket_context": {
                "issue_key": "OPS-42",
                "summary": "Auth outage",
                "status": "Open",
                "priority": "P1",
            },
            "feedback_context": {
                "confirmed_rcas": [{"candidate_id": "c1", "comments": "Confirmed"}],
                "rejected_rcas": [],
                "overridden_rcas": [],
            },
            "similar_incident_context": {
                "previous_investigation_summaries": [
                    {"investigation_id": "inv-old", "similarity_score": 0.8, "resolution_summary": "Rollback"}
                ],
                "historical_feedback": [],
                "historical_root_causes": [],
                "historical_remediation_actions": [
                    {"investigation_id": "inv-old", "action": "Rollback deployment"}
                ],
            },
            "multi_agent_findings": {
                "timeline_findings": {"summary": "Deploy preceded alert"},
                "deployment_findings": {},
                "infrastructure_findings": {},
                "incident_findings": {},
                "knowledge_findings": {},
                "rca_findings": {},
                "final_summary": "",
            },
        },
    )
    joined = " ".join(narrative.supporting_evidence)
    assert "Ticket Context" in joined
    assert "Historical Feedback" in joined
    assert "Historical incident" in joined
    assert "Agent Findings" in joined
    assert any("Historical remediation" in item for item in narrative.remediation_candidates)


def test_validate_output_rejects_short_or_contradicting_summary() -> None:
    from graphrag.output_validator import validate_output

    context = {
        "anomaly_id": "an-1",
        "candidates": [
            {"rank": 1, "file_id": "f1", "path": "/srv/auth/handler.py", "confidence": 0.8},
            {"rank": 2, "file_id": "f2", "path": "/srv/auth/other.py", "confidence": 0.4},
        ],
    }
    base = {
        "anomaly_id": "an-1",
        "primary_candidate": {
            "rank": 1,
            "file_id": "f1",
            "path": "/srv/auth/handler.py",
            "confidence": 0.8,
            "evidence_ref": "b1",
        },
        "ranked_hypotheses": [
            {
                "rank": 1,
                "file_id": "f1",
                "path": "/srv/auth/handler.py",
                "confidence": 0.8,
                "evidence_ref": "b1",
            }
        ],
        "evidence_highlights": ["Candidate rank 1: /srv/auth/handler.py (confidence 0.80)."],
        "confidence_alignment_note": "Deterministic ranking remains source of truth.",
        "optional_patch_direction": "Advisory: inspect handler timeouts.",
        "limitations": "",
    }

    short = dict(base)
    short["explanation_summary"] = "Too short."
    ok, errors = validate_output(short, context_pack=context)
    assert not ok
    assert any("extremely short" in e for e in errors)

    wrong_conf = dict(base)
    wrong_conf["explanation_summary"] = (
        "The incident centers on /srv/auth/handler.py. Deterministic RCA selected this path with "
        "confidence 0.55 even though the engine score is different. Stack frames and repeated "
        "timeouts support this candidate. Interpretation suggests a dependency delay. Additional "
        "deployment history should be reviewed before production changes are made to the service."
    )
    ok2, errors2 = validate_output(wrong_conf, context_pack=context)
    assert not ok2
    assert any("different confidence" in e for e in errors2)

    invent = dict(base)
    invent["explanation_summary"] = (
        "The failure is explained by /totally/invented/service/module.py rather than the selected "
        "candidate. Stack evidence and log keywords were reviewed. Interpretation points to a new "
        "component never seen in context. Confidence remains aligned with deterministic ranking at "
        "confidence 0.80 for the investigation narrative completeness requirements."
    )
    ok3, errors3 = validate_output(invent, context_pack=context)
    assert not ok3
    assert any("not present in deterministic context" in e for e in errors3)


def test_llm_config_keeps_low_temperature_and_token_budget() -> None:
    from graphrag.llm_client import LLMConfig

    cfg = LLMConfig.from_env()
    assert 0.1 <= cfg.temperature <= 0.3
    assert cfg.max_tokens >= 256
