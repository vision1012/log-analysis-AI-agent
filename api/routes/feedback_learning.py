"""Human feedback learning API for investigation RCA candidates."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps.auth import get_current_user
from api.services.feedback_learning_api_service import (
    submit_confirm_feedback,
    submit_override_feedback,
    submit_reject_feedback,
)
from schemas.users import UserResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


class FeedbackLearningBody(BaseModel):
    investigation_id: str = Field(..., min_length=1)
    candidate_id: str = Field(..., min_length=1)
    comments: str = ""


class OverrideFeedbackBody(FeedbackLearningBody):
    override_candidate_id: str = Field(..., min_length=1)


@router.post("/feedback/confirm")
async def confirm_feedback_endpoint(
    body: FeedbackLearningBody,
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, object]:
    """Record engineer confirmation of an RCA candidate for an investigation."""
    record = submit_confirm_feedback(
        investigation_id=body.investigation_id,
        candidate_id=body.candidate_id,
        user_id=current_user.user_id,
        comments=body.comments,
    )
    return {"ok": True, "feedback": record.model_dump()}


@router.post("/feedback/reject")
async def reject_feedback_endpoint(
    body: FeedbackLearningBody,
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, object]:
    """Record engineer rejection of an RCA candidate for an investigation."""
    record = submit_reject_feedback(
        investigation_id=body.investigation_id,
        candidate_id=body.candidate_id,
        user_id=current_user.user_id,
        comments=body.comments,
    )
    return {"ok": True, "feedback": record.model_dump()}


@router.post("/feedback/override")
async def override_feedback_endpoint(
    body: OverrideFeedbackBody,
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, object]:
    """Record engineer override: rejected suggested candidate in favor of another."""
    record = submit_override_feedback(
        investigation_id=body.investigation_id,
        candidate_id=body.candidate_id,
        override_candidate_id=body.override_candidate_id,
        user_id=current_user.user_id,
        comments=body.comments,
    )
    return {"ok": True, "feedback": record.model_dump()}
