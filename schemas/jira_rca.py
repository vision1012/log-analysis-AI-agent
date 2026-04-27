"""Schemas for JIRA-first RCA orchestration endpoint."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from schemas.jira import JiraExtractedHints, JiraNormalizedTicket


class JiraRcaRunRequest(BaseModel):
    """Input for ticket + logs RCA orchestration."""

    anomaly_id: Optional[str] = Field(
        default=None,
        description="Existing anomaly id used to invoke deterministic RCA engine",
    )
    ticket_key: str = Field(default="UNKNOWN", min_length=1)
    ticket: Optional[JiraNormalizedTicket] = None
    ticket_hints: Optional[JiraExtractedHints] = None
    ticket_summary: str = ""
    ticket_status: str = "unknown"
    ticket_priority: str = "unknown"
    extracted_hints: List[str] = Field(default_factory=list)
    log_content: str = Field(..., min_length=1)
    idempotency_key: Optional[str] = None
    force: bool = False

    @field_validator("log_content")
    @classmethod
    def log_content_not_blank(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("log_content must not be empty or whitespace-only")
        return s

    @field_validator("ticket_key")
    @classmethod
    def ticket_key_not_blank(cls, v: str) -> str:
        s = (v or "").strip()
        return s or "UNKNOWN"


class LogSignals(BaseModel):
    """Deterministic signals parsed from uploaded logs."""

    severity_counts: Dict[str, int] = Field(default_factory=dict)
    repeated_error_lines: List[str] = Field(default_factory=list)
    error_keywords: List[str] = Field(default_factory=list)
    service_names: List[str] = Field(default_factory=list)
    file_paths: List[str] = Field(default_factory=list)
    stack_traces: List[str] = Field(default_factory=list)
    time_window: Optional[Dict[str, str]] = None


class DerivedSignalBundle(BaseModel):
    """Merged ticket hints and log-derived signals."""

    ticket_hints: JiraExtractedHints
    log_signals: LogSignals
    merged: Dict[str, List[str]] = Field(default_factory=dict)


class JiraRcaResult(BaseModel):
    """Deterministic RCA run output used by JIRA-first endpoint."""

    anomaly_id: Optional[str] = None
    run_status: str
    run_id: Optional[str] = None
    rca_result: Dict[str, object] = Field(default_factory=dict)
    evidence_summary: Dict[str, object] = Field(default_factory=dict)


class JiraRcaExplanationPayload(BaseModel):
    """
    Grounded human-readable interpretation of deterministic RCA output.

    Evidence bundle references live only under ``rca.evidence_summary`` to avoid
    duplicating the same data. Assistive GraphRAG explanation may be partial or
    unavailable; see ``assist_status``.
    """

    root_cause: Dict[str, object] = Field(default_factory=dict)
    assist_status: Literal["ok", "partial", "unavailable"] = "unavailable"
    ticket_context_summary: Dict[str, object] = Field(default_factory=dict)
    log_signal_summary: Dict[str, object] = Field(default_factory=dict)
    explanation: str = ""
    remediation_suggestions: List[str] = Field(default_factory=list)
    confidence_note: str = ""


class RelationshipReadyBundle(BaseModel):
    """Lightweight graph-ready extraction output (no graph writes yet)."""

    ticket_key: str
    anomaly_id: Optional[str] = None
    rca_target_file: Optional[str] = None
    candidate_services: List[str] = Field(default_factory=list)
    candidate_errors: List[str] = Field(default_factory=list)
    candidate_file_paths: List[str] = Field(default_factory=list)
    entity_refs: Dict[str, List[str]] = Field(default_factory=dict)


class JiraRcaRunResponse(BaseModel):
    """Response for POST /api/v1/jira/rca/run."""

    ticket_summary: Dict[str, object]
    extracted_ticket_hints: JiraExtractedHints
    derived_log_signals: LogSignals
    derived_signal_bundle: DerivedSignalBundle
    rca: JiraRcaResult
    explanation_payload: JiraRcaExplanationPayload
    relationship_bundle: RelationshipReadyBundle
