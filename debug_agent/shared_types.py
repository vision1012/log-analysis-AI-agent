"""Shared types for the debug agent layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StepKind(str, Enum):
    """Kind of debug step."""
    RCA = "rca"
    EVIDENCE = "evidence"
    EXPLANATION = "explanation"
    TRIAGE = "triage"
    MEMORY = "memory"
    REMEDIATION = "remediation"
    REPORTING = "reporting"


class ReportStatus(str, Enum):
    """Status of an investigation report."""
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Root cause candidate (aligned with RCA/GraphRAG)
# ---------------------------------------------------------------------------


@dataclass
class RootCauseCandidate:
    """Single root cause candidate from deterministic RCA."""
    rank: int = 0
    file_id: str = ""
    path: str = ""
    confidence: float = 0.0
    evidence_ref: str = ""


# ---------------------------------------------------------------------------
# Internal payloads (agent outputs)
# ---------------------------------------------------------------------------


@dataclass
class TriageResult:
    """Output from triage agent."""
    anomaly_id: str = ""
    severity: str = ""
    service_ref: Optional[str] = None
    error_type: Optional[str] = None
    confidence_score: float = 0.0
    priority: str = ""
    summary: str = ""
    classification: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RCAResult:
    """Output from RCA agent (aligned with deterministic RCA)."""
    anomaly_id: str = ""
    run_id: Optional[str] = None
    candidates: list[RootCauseCandidate] = field(default_factory=list)
    primary: Optional[RootCauseCandidate] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidencePackage:
    """Output from evidence agent."""
    anomaly_id: str = ""
    bullets: list[str] = field(default_factory=list)
    signal_summaries: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryPackage:
    """Output from memory agent (session/historical context)."""
    anomaly_id: str = ""
    similar_incidents: list[dict[str, Any]] = field(default_factory=list)
    recurrence_score: float = 0.0
    historical_patterns_summary: str = ""
    prior_root_causes: list[dict[str, Any]] = field(default_factory=list)
    prior_attributions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplanationPackage:
    """Output from explanation agent (aligned with GraphRAG)."""
    anomaly_id: str = ""
    explanation_summary: str = ""
    confidence_alignment_note: str = ""
    evidence_highlights: list[str] = field(default_factory=list)
    limitations: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemediationPackage:
    """Output from remediation agent."""
    anomaly_id: str = ""
    steps: list[str] = field(default_factory=list)
    optional_patch_direction: str = ""
    confidence_note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportingPackage:
    """Output from reporting agent."""
    anomaly_id: str = ""
    final_report_summary: str = ""
    investigation_report: dict[str, Any] = field(default_factory=dict)
    executive_summary: str = ""
    final_summary: str = ""
    status: ReportStatus = ReportStatus.COMPLETED
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Unified investigation report
# ---------------------------------------------------------------------------


@dataclass
class InvestigationReport:
    """Unified investigation report (final debug session output)."""
    anomaly_id: str = ""
    run_id: Optional[str] = None
    created_at: str = ""
    status: ReportStatus = ReportStatus.COMPLETED
    triage_summary: str = ""
    root_cause_candidates: list[RootCauseCandidate] = field(default_factory=list)
    primary_candidate: Optional[RootCauseCandidate] = None
    confidence_summary: str = ""
    evidence_highlights: list[str] = field(default_factory=list)
    similar_incidents: list[dict[str, Any]] = field(default_factory=list)
    historical_patterns_summary: str = ""
    recurrence_signals: dict[str, Any] = field(default_factory=dict)
    explanation_summary: str = ""
    remediation_steps: list[str] = field(default_factory=list)
    optional_patch_direction: str = ""
    final_report_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-serializable dict."""
        return {
            "anomaly_id": self.anomaly_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "status": self.status.value,
            "triage_summary": self.triage_summary,
            "root_cause_candidates": [
                {
                    "rank": c.rank,
                    "file_id": c.file_id,
                    "path": c.path,
                    "confidence": c.confidence,
                    "evidence_ref": c.evidence_ref,
                }
                for c in self.root_cause_candidates
            ],
            "primary_candidate": (
                {
                    "rank": self.primary_candidate.rank,
                    "file_id": self.primary_candidate.file_id,
                    "path": self.primary_candidate.path,
                    "confidence": self.primary_candidate.confidence,
                    "evidence_ref": self.primary_candidate.evidence_ref,
                }
                if self.primary_candidate else None
            ),
            "confidence_summary": self.confidence_summary,
            "evidence_highlights": self.evidence_highlights,
            "similar_incidents": self.similar_incidents,
            "historical_patterns_summary": self.historical_patterns_summary,
            "recurrence_signals": self.recurrence_signals,
            "explanation_summary": self.explanation_summary,
            "remediation_steps": self.remediation_steps,
            "optional_patch_direction": self.optional_patch_direction,
            "final_report_summary": self.final_report_summary,
        }


# ---------------------------------------------------------------------------
# Context and step result
# ---------------------------------------------------------------------------


@dataclass
class DebugContext:
    """Context passed between agents during a debug session."""
    anomaly_id: str = ""
    run_id: Optional[str] = None
    trace_ref: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of a single agent step."""
    step_kind: StepKind
    success: bool = False
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
