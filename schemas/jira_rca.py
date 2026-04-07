"""Schemas for JIRA-first RCA orchestration endpoint."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from schemas.jira import JiraExtractedHints, JiraNormalizedTicket


class JiraRcaRunRequest(BaseModel):
    """Input for ticket + logs RCA orchestration."""

    anomaly_id: Optional[str] = Field(
        default=None,
        description="Existing anomaly id used to invoke deterministic RCA engine",
    )
    ticket_key: Optional[str] = None
    ticket: Optional[JiraNormalizedTicket] = None
    ticket_hints: Optional[JiraExtractedHints] = None
    log_content: str = Field(..., min_length=1)
    idempotency_key: Optional[str] = None
    force: bool = False


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

    anomaly_id: str
    run_status: str
    run_id: Optional[str] = None
    rca_result: Dict[str, object] = Field(default_factory=dict)
    evidence_summary: Dict[str, object] = Field(default_factory=dict)


class JiraRcaRunResponse(BaseModel):
    """Response for POST /api/v1/jira/rca/run."""

    ticket_summary: Dict[str, object]
    extracted_ticket_hints: JiraExtractedHints
    derived_log_signals: LogSignals
    derived_signal_bundle: DerivedSignalBundle
    rca: JiraRcaResult
