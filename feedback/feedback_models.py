"""Models for human feedback learning on investigation RCA candidates."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    OVERRIDDEN = "OVERRIDDEN"


class FeedbackRecord(BaseModel):
    """Persisted engineer feedback on an RCA candidate."""

    feedback_id: str
    investigation_id: str
    candidate_id: str
    feedback_type: str
    comments: str = ""
    user_id: str = ""
    created_at: str
    override_candidate_id: str = ""


class CandidateFeedbackCount(BaseModel):
    """Aggregate feedback count for a candidate."""

    candidate_id: str
    count: int


class HistoricalFeedback(BaseModel):
    """Feedback summary attached to similar incident search results."""

    feedback_id: str
    candidate_id: str
    feedback_type: str
    comments: str = ""
    user_id: str = ""
    created_at: str
    override_candidate_id: str = ""
