"""Typed schema helpers for LangChain-powered LLM agent outputs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CandidateRefSchema(BaseModel):
    """Minimal candidate reference aligned with deterministic RCA candidate shape."""

    model_config = ConfigDict(extra="ignore")

    rank: int = 0
    file_id: str = ""
    path: str = ""
    confidence: float = 0.0
    evidence_ref: str = ""
    hypothesis: str = ""


class ExplanationLLMOutputSchema(BaseModel):
    """LLM explanation payload aligned with ExplanationPackage-compatible fields."""

    model_config = ConfigDict(extra="ignore")

    anomaly_id: str
    primary_candidate: CandidateRefSchema = Field(default_factory=CandidateRefSchema)
    ranked_hypotheses: list[CandidateRefSchema] = Field(default_factory=list)
    explanation_summary: str = ""
    confidence_alignment_note: str = ""
    evidence_highlights: list[str] = Field(default_factory=list)
    optional_patch_direction: str = ""
    limitations: str = ""


class RemediationLLMOutputSchema(BaseModel):
    """LLM remediation payload aligned with RemediationPackage fields."""

    model_config = ConfigDict(extra="ignore")

    remediation_steps: list[str] = Field(default_factory=list)
    reversible_mitigation_suggestions: list[str] = Field(default_factory=list)
    validation_suggestions: list[str] = Field(default_factory=list)
    optional_patch_direction: str = ""
    confidence_note: str = ""


class ReportingLLMOutputSchema(BaseModel):
    """LLM report-formatting payload aligned with ReportingPackage summary fields."""

    model_config = ConfigDict(extra="ignore")

    final_report_summary: str
    executive_summary: str
    investigation_narrative: str = ""


def parse_explanation_llm_output(raw: dict[str, Any]) -> Optional[ExplanationLLMOutputSchema]:
    """Validate explanation LLM output and return typed schema, else None."""
    try:
        cleaned = dict(raw)
        for key in (
            "anomaly_id",
            "explanation_summary",
            "confidence_alignment_note",
            "optional_patch_direction",
            "limitations",
        ):
            if cleaned.get(key) is None:
                cleaned[key] = ""
        return ExplanationLLMOutputSchema.model_validate(cleaned)
    except ValidationError:
        return None


def parse_remediation_llm_output(raw: dict[str, Any]) -> Optional[RemediationLLMOutputSchema]:
    """Validate remediation LLM output and return typed schema, else None."""
    try:
        cleaned = dict(raw)
        for key in (
            "optional_patch_direction",
            "confidence_note",
        ):
            if cleaned.get(key) is None:
                cleaned[key] = ""
        return RemediationLLMOutputSchema.model_validate(cleaned)
    except ValidationError:
        return None


def parse_reporting_llm_output(raw: dict[str, Any]) -> Optional[ReportingLLMOutputSchema]:
    """Validate reporting LLM output and return typed schema, else None."""
    try:
        cleaned = dict(raw)
        for key in ("final_report_summary", "executive_summary", "investigation_narrative"):
            if cleaned.get(key) is None:
                cleaned[key] = ""
        return ReportingLLMOutputSchema.model_validate(cleaned)
    except ValidationError:
        return None
