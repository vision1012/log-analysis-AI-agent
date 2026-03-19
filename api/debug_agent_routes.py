"""
Debug-agent API endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from debug_agent.orchestrator import run_debug_session

logger = logging.getLogger(__name__)
router = APIRouter()

_LATEST_STATUS: dict[str, dict[str, Any]] = {}


class DebugAgentRunRequest(BaseModel):
    """Request body for debug-agent run endpoint."""

    anomaly_id: str


@router.post("/debug-agent/run")
async def run_debug_agent(body: DebugAgentRunRequest):
    """
    Run full debug-agent pipeline for one anomaly.

    Returns structured investigation output from orchestrator/reporting layer.
    """
    anomaly_id = (body.anomaly_id or "").strip()
    if not anomaly_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "bad_request", "message": "anomaly_id is required"},
        )

    logger.info("api.debug_agent.run.start anomaly_id=%s", anomaly_id)
    _LATEST_STATUS[anomaly_id] = {
        "anomaly_id": anomaly_id,
        "status": "running",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = run_debug_session(anomaly_id)
        if not isinstance(result, dict) or not isinstance(result.get("investigation_report"), dict):
            raise RuntimeError("debug agent returned invalid structured output")
        run_status = str(result.get("status") or "unknown")
        report = result.get("investigation_report") or {}
        _LATEST_STATUS[anomaly_id] = {
            "anomaly_id": anomaly_id,
            "status": run_status,
            "run_id": result.get("run_id"),
            "final_report_summary": report.get("final_report_summary"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "api.debug_agent.run.done anomaly_id=%s status=%s run_id=%s report_keys=%s",
            anomaly_id,
            run_status,
            result.get("run_id"),
            len(report.keys()) if isinstance(report, dict) else 0,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api.debug_agent.run.error anomaly_id=%s error=%s", anomaly_id, str(exc))
        _LATEST_STATUS[anomaly_id] = {
            "anomaly_id": anomaly_id,
            "status": "failed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "debug_agent_failed", "message": str(exc)},
        ) from exc


@router.get("/debug-agent/status/{anomaly_id}")
async def get_debug_agent_status(
    anomaly_id: str = Path(..., description="Anomaly ID"),
):
    """
    Optional status endpoint for latest debug-agent run state.

    Returns lightweight in-process status if present.
    """
    logger.info("api.debug_agent.status.get anomaly_id=%s", anomaly_id)
    state = _LATEST_STATUS.get(anomaly_id)
    if state:
        return state
    return {
        "anomaly_id": anomaly_id,
        "status": "unknown",
        "updated_at": None,
    }

