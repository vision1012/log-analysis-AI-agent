"""Investigation report data models."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class SimilarIncidentEntry(BaseModel):
    """Similar incident summary for export."""

    investigation_id: str
    similarity_score: float = 0.0
    root_cause: str = ""
    confidence: float = 0.0
    resolution_summary: str = ""
    matched_factors: List[str] = Field(default_factory=list)


class FeedbackHistoryEntry(BaseModel):
    """Feedback record summary for export."""

    feedback_id: str
    candidate_id: str
    feedback_type: str
    comments: str = ""
    user_id: str = ""
    created_at: str = ""


class RunbookEntry(BaseModel):
    """Runbook summary for export."""

    title: str = ""
    service_name: str = ""
    summary: str = ""
    url: str = ""


class ArchitectureReferenceEntry(BaseModel):
    """Architecture document summary for export."""

    title: str = ""
    summary: str = ""
    service: str = ""
    subsystem: str = ""
    relevance: float = 0.0
    document_url: str = ""


class EvidenceCoverageSection(BaseModel):
    """MCP evidence coverage summary for export."""

    coverage_score: float = 0.0
    coverage_level: str = "low"
    available_sources: List[str] = Field(default_factory=list)
    missing_sources: List[str] = Field(default_factory=list)
    confidence_limitations: List[str] = Field(default_factory=list)


class KeywordEvidenceSection(BaseModel):
    """Keyword alignment evidence for export."""

    candidate_path: str = ""
    keyword_score: float = 0.0
    matched_keywords: List[str] = Field(default_factory=list)
    keyword_categories: List[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    """Unified investigation report assembled from all data sources."""

    investigation_id: str
    title: str
    executive_summary: str
    timeline_summary: str
    graph_summary: str
    root_cause: str
    confidence: float
    confidence_reasoning: str
    similar_incidents: List[SimilarIncidentEntry] = Field(default_factory=list)
    feedback_history: List[FeedbackHistoryEntry] = Field(default_factory=list)
    runbooks: List[RunbookEntry] = Field(default_factory=list)
    architecture_references: List[ArchitectureReferenceEntry] = Field(default_factory=list)
    remediation_steps: List[str] = Field(default_factory=list)
    multi_agent_summary: str = ""
    evidence_coverage: EvidenceCoverageSection = Field(default_factory=EvidenceCoverageSection)
    keyword_evidence: KeywordEvidenceSection = Field(default_factory=KeywordEvidenceSection)
    generated_at: str

    def to_export_dict(self) -> dict[str, Any]:
        """Serialize for JSON API responses."""
        return self.model_dump()
