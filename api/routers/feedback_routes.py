"""
Feedback API endpoints: confirm, reject, reject all, rollback.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from api.deps.auth import get_current_user
from api.services.feedback_service import (
    confirm_candidate,
    reject_all,
    reject_candidate,
    rollback,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


class ConfirmRejectBody(BaseModel):
    """Request body for confirm/reject (candidate-specific)."""
    file_id: str
    run_id: str
    actor_id: str
    reason: str = ""


class FeedbackBody(BaseModel):
    """Request body for reject-all/rollback."""
    actor_id: str
    reason: str = ""


@router.post("/feedback/confirm/{anomaly_id}")
async def confirm_candidate_endpoint(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: ConfirmRejectBody = ...,
):
    """Confirm candidate: selected -> accepted, all others -> rejected."""
    confirm_candidate(
        anomaly_id, body.file_id, body.run_id,
        actor_id=body.actor_id, reason=body.reason,
    )
    return {"ok": True, "status": "accepted"}


@router.post("/feedback/reject/{anomaly_id}")
async def reject_candidate_endpoint(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: ConfirmRejectBody = ...,
):
    """Reject only that candidate."""
    reject_candidate(
        anomaly_id, body.file_id, body.run_id,
        actor_id=body.actor_id, reason=body.reason,
    )
    return {"ok": True, "status": "rejected"}


@router.post("/feedback/reject-all/{anomaly_id}")
async def reject_all_endpoint(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: FeedbackBody = ...,
):
    """Reject all candidates for anomaly."""
    reject_all(anomaly_id, actor_id=body.actor_id, reason=body.reason)
    return {"ok": True}


@router.post("/feedback/rollback/{anomaly_id}")
async def rollback_endpoint(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: FeedbackBody = ...,
):
    """Rollback: accepted -> rejected."""
    rollback(anomaly_id, actor_id=body.actor_id, reason=body.reason)
    return {"ok": True}
