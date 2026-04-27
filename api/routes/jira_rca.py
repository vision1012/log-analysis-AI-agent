"""JIRA-first RCA run endpoint (ticket + logs -> deterministic RCA)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from api.services.jira_rca_orchestration_service import run_jira_rca
from schemas.jira_rca import JiraRcaRunRequest
from services.llm_client import call_llm

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/jira/rca/run")
async def run_jira_rca_endpoint(request: Request) -> dict[str, object]:
    """JIRA-first RCA: ticket + logs -> deterministic RCA + explanation."""
    body = await _coerce_jira_rca_request(request)

    print("----- RCA REQUEST RECEIVED -----")
    print("ticket_key:", body.ticket_key)
    print("log_content length:", len(body.log_content))
    print("log_content preview:", (body.log_content or "")[:200])

    rca_response = run_jira_rca(body)

    signals = {}
    try:
        signals = dict((rca_response.derived_log_signals.model_dump() if hasattr(rca_response, "derived_log_signals") else {}))
    except Exception:
        signals = {}

    candidates: list[dict[str, object]] = []
    try:
        candidates = list((rca_response.rca.rca_result or {}).get("candidate_root_causes") or [])
    except Exception:
        candidates = []

    root_cause = None
    top_candidate: dict[str, object] = {}

    if candidates and len(candidates) > 0:
        top_candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        root_cause = (
            top_candidate.get("file_path")
            or top_candidate.get("value")
            or top_candidate.get("file")
            or top_candidate.get("path")
            or top_candidate.get("node")
            or "unknown"
        )
    else:
        root_cause = "No candidate found"
    logger.debug("Top candidate: %s", top_candidate)
    logger.debug("Resolved root cause: %s", root_cause)
    print("DEBUG -> root_cause:", root_cause)

    top_score = top_candidate.get("score", top_candidate.get("confidence", 0.5))
    if root_cause:
        explanation = call_llm(str(root_cause))
    else:
        explanation = "No root cause available"
    print("DEBUG -> LLM output:", explanation)

    return {
        "root_cause": root_cause,
        "primary_root_cause": root_cause,
        "confidence": top_score,
        "evidence": signals,
        "explanation": explanation,
    }


async def _coerce_jira_rca_request(request: Request) -> JiraRcaRunRequest:
    content_type = (request.headers.get("content-type") or "").lower()
    logger.info("jira_rca.request.content_type content_type=%s", content_type)
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_jira_rca_request", "message": "JSON body must be an object"},
            )
        logger.info(
            "jira_rca.request.json has_log_content=%s log_content_len=%d",
            isinstance(payload.get("log_content"), str) and bool(payload.get("log_content", "").strip()),
            len(str(payload.get("log_content") or "")),
        )
        try:
            return JiraRcaRunRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_jira_rca_request", "message": str(exc)},
            ) from exc

    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "unsupported_content_type",
                "message": "Use application/json or multipart/form-data",
            },
        )

    form = await request.form()
    anomaly_id = _form_str(form.get("anomaly_id"))
    ticket_key = _form_str(form.get("ticket_key"))
    ticket = _form_str(form.get("ticket"))
    ticket_hints = _form_str(form.get("ticket_hints"))
    log_content = _form_str(form.get("log_content"))
    idempotency_key = _form_str(form.get("idempotency_key"))
    force = _form_bool(form.get("force"))
    log_file_obj = form.get("log_file")
    log_file = log_file_obj if isinstance(log_file_obj, UploadFile) or hasattr(log_file_obj, "read") else None

    file_content = ""
    if log_file is not None:
        raw = await log_file.read()
        file_content = raw.decode("utf-8", errors="replace")
    final_log_content = (log_content or "").strip() or file_content.strip()
    logger.info(
        "jira_rca.request.multipart has_log_content=%s log_content_len=%d has_log_file=%s file_len=%d",
        bool((log_content or "").strip()),
        len(log_content or ""),
        log_file is not None,
        len(file_content),
    )
    payload: dict[str, object] = {
        "anomaly_id": anomaly_id,
        "ticket_key": ticket_key,
        "log_content": final_log_content,
        "idempotency_key": idempotency_key,
        "force": bool(force) if force is not None else False,
    }
    if ticket:
        payload["ticket"] = json.loads(ticket)
    if ticket_hints:
        payload["ticket_hints"] = json.loads(ticket_hints)
    try:
        return JiraRcaRunRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_jira_rca_request", "message": str(exc)},
        ) from exc


def _form_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text


def _form_bool(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}
