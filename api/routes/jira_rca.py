"""JIRA-first RCA run endpoint (ticket + logs -> deterministic RCA)."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import ValidationError
from starlette.requests import Request

from api.deps.auth import get_current_user
from api.services.jira_rca_orchestration_service import NoUsefulSignalsError, run_jira_rca
from schemas.jira_rca import JiraRcaRunRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/jira/rca/run", dependencies=[Depends(get_current_user)])
async def run_jira_rca_endpoint(request: Request) -> dict[str, object]:
    """JIRA-first RCA: ticket + logs -> deterministic RCA + GraphRAG explanation."""
    body = await _coerce_jira_rca_request(request)

    try:
        rca_response = run_jira_rca(body)
    except NoUsefulSignalsError:
        fallback_explanation = (
            "Deterministic RCA identified no useful signals from the provided log content."
        )
        return {
            "rca": {
                "anomaly_id": body.anomaly_id,
                "run_status": "completed",
                "run_id": body.idempotency_key or "",
                "rca_result": {"candidate_root_causes": []},
                "evidence_summary": {"bundle_count": 0, "evidence_refs": [], "evidence_highlights": []},
            },
            "derived_log_signals": {},
            "evidence_summary": {"bundle_count": 0, "evidence_refs": [], "evidence_highlights": []},
            "explanation_payload": {
                "root_cause": {"source": "unavailable", "confidence": 0.0},
                "assist_status": "unavailable",
                "ticket_context_summary": {
                    "ticket_key": body.ticket_key,
                    "summary": body.ticket_summary,
                    "status": body.ticket_status,
                    "priority": body.ticket_priority,
                },
                "log_signal_summary": {},
                "explanation": fallback_explanation,
                "remediation_suggestions": [],
                "confidence_note": "No deterministic signals were available.",
            },
            "remediation_suggestions": [],
            "primary_root_cause": "No candidate found",
            "confidence": 0.0,
            "root_cause": "No candidate found",
            "evidence": {},
            "explanation": fallback_explanation,
        }

    response_payload = rca_response.model_dump() if hasattr(rca_response, "model_dump") else dict(rca_response)
    explanation_payload = response_payload.get("explanation_payload") or {}
    if not isinstance(explanation_payload, dict):
        explanation_payload = {}

    candidates: list[dict[str, object]] = []
    try:
        candidates = list((response_payload.get("rca") or {}).get("rca_result", {}).get("candidate_root_causes") or [])
    except Exception:
        candidates = []

    top_candidate: dict[str, object] = {}
    if candidates and isinstance(candidates[0], dict):
        top_candidate = candidates[0]

    root_cause = (
        top_candidate.get("file_path")
        or top_candidate.get("value")
        or top_candidate.get("file")
        or top_candidate.get("path")
        or top_candidate.get("node")
        or top_candidate.get("file_id")
        or "No candidate found"
    )
    top_score = top_candidate.get("score", top_candidate.get("confidence", 0.0))

    signals: dict[str, object] = {}
    derived = response_payload.get("derived_log_signals")
    if isinstance(derived, dict):
        signals = dict(derived)

    explanation = str(explanation_payload.get("explanation") or "").strip()
    if not explanation:
        explanation = (
            f"Deterministic RCA identified {root_cause} as the leading candidate."
            if root_cause != "No candidate found"
            else "No root cause available"
        )

    response_payload.update(
        {
            "evidence_summary": (response_payload.get("rca") or {}).get("evidence_summary", {}),
            "remediation_suggestions": explanation_payload.get("remediation_suggestions", []),
            "root_cause": root_cause,
            "primary_root_cause": root_cause,
            "confidence": top_score,
            "evidence": signals,
            "explanation": explanation,
        }
    )
    return response_payload


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
