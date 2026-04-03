"""
RCA API endpoints: run, rerun, results, run-status.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.rate_limit.deps import rate_limit
from pydantic import BaseModel

from api.services.rca_service import (
    get_rca_explanation,
    get_rca_result_view,
    get_rca_results,
    get_rca_run_status,
    trigger_manual_rca,
)

router = APIRouter()


class RunRequest(BaseModel):
    """Request body for run/rerun endpoints."""
    idempotency_key: str


@router.post("/rca/run/{anomaly_id}")
async def run_rca(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: RunRequest = ...,
):
    """Manual trigger RCA. Requires idempotency_key in body."""
    result = trigger_manual_rca(anomaly_id, body.idempotency_key, force=False)
    if result.get("status") == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "rca_rejected", "message": result.get("reason", "Locked")},
        )
    if result.get("status") == "blocked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "rca_blocked", "message": result.get("reason", "Gate failed")},
        )
    return result


@router.post("/rca/rerun/{anomaly_id}")
async def rerun_rca(
    anomaly_id: str = Path(..., description="Anomaly ID"),
    body: RunRequest = ...,
):
    """Rerun RCA with idempotency key. Supersedes prior attributions (force=True)."""
    result = trigger_manual_rca(anomaly_id, body.idempotency_key, force=True)
    if result.get("status") == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "rca_rejected", "message": result.get("reason", "Locked")},
        )
    if result.get("status") == "blocked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "rca_blocked", "message": result.get("reason", "Gate failed")},
        )
    return result


@router.get(
    "/rca/results/{anomaly_id}",
    dependencies=[Depends(rate_limit("rca_results"))],
)
async def get_results(
    anomaly_id: str = Path(..., description="Anomaly ID"),
):
    """Fetch current candidates/accepted RCA for an anomaly."""
    candidates = get_rca_results(anomaly_id)
    return {"anomaly_id": anomaly_id, "candidates": candidates}


@router.get("/rca/result-view/{anomaly_id}")
async def get_result_view(
    anomaly_id: str = Path(..., description="Anomaly ID"),
):
    """Fetch RCA results in structured view (anomaly_id, current_status, accepted_root_cause, etc.)."""
    return get_rca_result_view(anomaly_id)


@router.get("/rca/run-status/{anomaly_id}")
async def get_run_status(
    anomaly_id: str = Path(..., description="Anomaly ID"),
):
    """Get current lock/run state for an anomaly."""
    return get_rca_run_status(anomaly_id)


@router.get(
    "/rca/explanation/{anomaly_id}",
    dependencies=[Depends(rate_limit("rca_explanation"))],
)
async def get_explanation(
    anomaly_id: str = Path(..., description="Anomaly ID"),
):
    """Generate GraphRAG explanation from latest deterministic RCA candidates."""
    return get_rca_explanation(anomaly_id)
