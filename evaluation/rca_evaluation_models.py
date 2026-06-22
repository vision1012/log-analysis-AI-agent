"""Response models for RCA evaluation dashboard APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from feedback.feedback_models import CandidateFeedbackCount


class RcaEvaluationSummary(BaseModel):
    total_investigations: int = 0
    total_feedback_count: int = 0
    confirmed_count: int = 0
    rejected_count: int = 0
    overridden_count: int = 0
    confirmation_rate: float = 0.0
    rejection_rate: float = 0.0
    override_rate: float = 0.0
    average_confidence: float = 0.0
    high_confidence_accuracy: float = 0.0
    most_confirmed_candidates: list[CandidateFeedbackCount] = Field(default_factory=list)
    most_rejected_candidates: list[CandidateFeedbackCount] = Field(default_factory=list)


class ServiceAccuracyRow(BaseModel):
    service_name: str
    total_feedback: int = 0
    confirmed_count: int = 0
    rejected_count: int = 0
    overridden_count: int = 0
    confirmation_rate: float = 0.0


class ConfidenceLevelAccuracy(BaseModel):
    confidence_level: str
    total_feedback: int = 0
    confirmed_count: int = 0
    confirmation_rate: float = 0.0


class ConfidenceMetrics(BaseModel):
    average_confidence: float = 0.0
    high_confidence_accuracy: float = 0.0
    accuracy_by_confidence_level: list[ConfidenceLevelAccuracy] = Field(default_factory=list)


class FeedbackTrendPoint(BaseModel):
    date: str
    total_count: int = 0
    confirmed_count: int = 0
    rejected_count: int = 0
    overridden_count: int = 0
