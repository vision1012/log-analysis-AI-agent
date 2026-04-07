"""JIRA-first RCA orchestration: ticket + logs -> deterministic RCA entry."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from collections import Counter

from artifacts.investigation_store import LocalFileInvestigationStore
from api.services.jira_service import fetch_ticket_context
from api.services.rca_service import get_rca_result_view, trigger_manual_rca
from schemas.jira import JiraExtractedHints, JiraNormalizedTicket
from schemas.jira_rca import (
    DerivedSignalBundle,
    JiraRcaResult,
    JiraRcaRunRequest,
    JiraRcaRunResponse,
    LogSignals,
)

_LEVEL_PATTERNS = {
    "critical": re.compile(r"\b(critical|fatal|panic)\b", re.IGNORECASE),
    "error": re.compile(r"\b(error|err|exception|traceback)\b", re.IGNORECASE),
    "warning": re.compile(r"\b(warn|warning)\b", re.IGNORECASE),
    "info": re.compile(r"\binfo\b", re.IGNORECASE),
    "debug": re.compile(r"\bdebug\b", re.IGNORECASE),
}
_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_UNIX_PATH_RE = re.compile(r"(?:/[A-Za-z0-9._-]+)+")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+")
_SERVICE_RE = re.compile(
    r"\b([a-z0-9][a-z0-9_-]*(?:service|svc|api|worker|backend|frontend))\b", re.IGNORECASE
)

logger = logging.getLogger(__name__)


class JiraRcaOrchestrationError(Exception):
    """Base class for JIRA-RCA orchestration errors."""


class MissingTicketContextError(JiraRcaOrchestrationError):
    """Raised when request does not contain usable ticket context."""


class EmptyLogContentError(JiraRcaOrchestrationError):
    """Raised when uploaded log text is empty."""


class NoUsefulSignalsError(JiraRcaOrchestrationError):
    """Raised when no deterministic signals can be extracted from logs."""


class RcaUnableToRankCandidateError(JiraRcaOrchestrationError):
    """Raised when RCA cannot produce candidate ranking."""


def run_jira_rca(request: JiraRcaRunRequest) -> JiraRcaRunResponse:
    """Execute JIRA-first orchestration while reusing existing deterministic RCA."""
    logger.info(
        "jira_rca.run.start anomaly_id=%s ticket_key=%s",
        (request.anomaly_id or "").strip(),
        (request.ticket_key or (request.ticket.ticket_key if request.ticket else "")),
    )
    ticket, ticket_hints = _resolve_ticket_context(request)
    log_signals = _derive_log_signals(request.log_content)
    logger.info(
        "jira_rca.signals.derived ticket_key=%s severity_types=%d repeated_error_lines=%d services=%d file_paths=%d",
        ticket.ticket_key,
        len(log_signals.severity_counts),
        len(log_signals.repeated_error_lines),
        len(log_signals.service_names),
        len(log_signals.file_paths),
    )
    if _signals_empty(log_signals):
        logger.warning("jira_rca.signals.empty ticket_key=%s", ticket.ticket_key)
        raise NoUsefulSignalsError("no useful signals found in uploaded log content")

    bundle = _merge_signals(ticket_hints, log_signals)
    anomaly_id = (request.anomaly_id or "").strip()
    if not anomaly_id:
        raise MissingTicketContextError(
            "missing anomaly_id: existing deterministic RCA engine requires a target anomaly"
        )
    run_id = request.idempotency_key or _default_idempotency_key(ticket.ticket_key, request.log_content)

    logger.info(
        "jira_rca.engine.invoke anomaly_id=%s run_id=%s force=%s",
        anomaly_id,
        run_id,
        request.force,
    )
    rca_run = trigger_manual_rca(anomaly_id, run_id, force=request.force)
    run_status = str(rca_run.get("status") or "")
    if run_status in {"blocked", "rejected"}:
        logger.warning(
            "jira_rca.engine.blocked anomaly_id=%s run_id=%s status=%s",
            anomaly_id,
            run_id,
            run_status,
        )
        raise RcaUnableToRankCandidateError(str(rca_run.get("reason") or "rca run blocked"))

    rca_view = get_rca_result_view(anomaly_id)
    accepted = rca_view.get("accepted_root_cause")
    candidates = rca_view.get("candidate_root_causes") or []
    if not accepted and not candidates:
        logger.warning("jira_rca.engine.no_candidates anomaly_id=%s run_id=%s", anomaly_id, run_id)
        raise RcaUnableToRankCandidateError("RCA unable to rank candidate for anomaly")

    evidence_refs = rca_view.get("evidence_refs") or []
    evidence_summary = {
        "bundle_count": len(evidence_refs),
        "evidence_refs": evidence_refs,
        "latest_run_id": rca_view.get("latest_run_id"),
    }
    investigation_id = _persist_investigation_trace(
        ticket=ticket,
        anomaly_id=anomaly_id,
        run_id=str(rca_run.get("run_id") or run_id),
        run_status=run_status or "completed",
        bundle=bundle,
        rca_view=rca_view,
    )
    evidence_summary["investigation_id"] = investigation_id
    logger.info(
        "jira_rca.run.success anomaly_id=%s run_id=%s investigation_id=%s",
        anomaly_id,
        str(rca_run.get("run_id") or run_id),
        investigation_id,
    )

    return JiraRcaRunResponse(
        ticket_summary={
            "ticket_key": ticket.ticket_key,
            "ticket_id": ticket.ticket_id,
            "summary": ticket.summary,
            "status": ticket.status,
            "priority": ticket.priority,
            "url": ticket.url,
        },
        extracted_ticket_hints=ticket_hints,
        derived_log_signals=log_signals,
        derived_signal_bundle=bundle,
        rca=JiraRcaResult(
            anomaly_id=anomaly_id,
            run_status=run_status or "completed",
            run_id=str(rca_run.get("run_id") or ""),
            rca_result=rca_view,
            evidence_summary=evidence_summary,
        ),
    )


def _resolve_ticket_context(request: JiraRcaRunRequest) -> tuple[JiraNormalizedTicket, JiraExtractedHints]:
    if request.ticket:
        hints = request.ticket_hints or _extract_hints_from_ticket_text(request.ticket)
        return request.ticket, hints
    if request.ticket_key:
        fetched = fetch_ticket_context(request.ticket_key)
        return fetched.ticket, fetched.hints
    raise MissingTicketContextError("missing ticket context: provide ticket or ticket_key")


def _extract_hints_from_ticket_text(ticket: JiraNormalizedTicket) -> JiraExtractedHints:
    text = " ".join([ticket.summary, ticket.description, ticket.comments_text]).strip()
    services = _uniq([m.lower() for m in _SERVICE_RE.findall(text)])
    envs = _uniq(
        [
            env
            for env in ["prod", "production", "staging", "stage", "dev", "qa", "test", "uat", "sandbox"]
            if re.search(rf"\b{re.escape(env)}\b", text, re.IGNORECASE)
        ]
    )
    file_paths = _uniq(_UNIX_PATH_RE.findall(text) + _WIN_PATH_RE.findall(text))
    keyword_bank = ["error", "exception", "timeout", "failed", "stacktrace", "panic", "503", "502", "504"]
    lower = text.lower()
    keywords = _uniq([k for k in keyword_bank if k in lower])
    return JiraExtractedHints(
        service_names=services,
        environment_names=envs,
        file_paths=file_paths,
        error_keywords=keywords,
        labels=ticket.labels,
    )


def _derive_log_signals(log_content: str) -> LogSignals:
    content = (log_content or "").strip()
    if not content:
        logger.warning("jira_rca.logs.empty")
        raise EmptyLogContentError("empty log file/content")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]

    severity_counts: dict[str, int] = {}
    for level, pattern in _LEVEL_PATTERNS.items():
        count = sum(1 for ln in lines if pattern.search(ln))
        if count > 0:
            severity_counts[level] = count

    err_lines = [ln for ln in lines if _LEVEL_PATTERNS["error"].search(ln) or _LEVEL_PATTERNS["critical"].search(ln)]
    repeated_error_lines = [txt for txt, n in Counter(err_lines).items() if n > 1]

    lower_blob = content.lower()
    keyword_bank = [
        "timeout",
        "connection refused",
        "exception",
        "traceback",
        "failed",
        "error",
        "nullpointer",
        "outofmemory",
        "oom",
        "503",
        "502",
        "504",
    ]
    error_keywords = _uniq([k for k in keyword_bank if k in lower_blob])
    service_names = _uniq([m.lower() for m in _SERVICE_RE.findall(content)])
    file_paths = _uniq(_UNIX_PATH_RE.findall(content) + _WIN_PATH_RE.findall(content))

    stack_blocks = _extract_stack_traces(lines)
    time_window = _extract_time_window(content)

    return LogSignals(
        severity_counts=severity_counts,
        repeated_error_lines=repeated_error_lines[:20],
        error_keywords=error_keywords,
        service_names=service_names,
        file_paths=file_paths[:100],
        stack_traces=stack_blocks[:5],
        time_window=time_window,
    )


def _extract_stack_traces(lines: list[str]) -> list[str]:
    traces: list[str] = []
    current: list[str] = []
    for ln in lines:
        looks_like_stack = (
            ln.startswith("Traceback ")
            or ln.startswith("at ")
            or bool(re.search(r"\bFile \".+\", line \d+", ln))
            or bool(re.search(r"\w+Error: ", ln))
        )
        if looks_like_stack:
            current.append(ln)
            continue
        if current:
            traces.append("\n".join(current))
            current = []
    if current:
        traces.append("\n".join(current))
    return traces


def _extract_time_window(content: str) -> dict[str, str] | None:
    ts = _TS_RE.findall(content)
    if not ts:
        return None
    return {"start": min(ts), "end": max(ts)}


def _merge_signals(ticket_hints: JiraExtractedHints, log_signals: LogSignals) -> DerivedSignalBundle:
    merged = {
        "service_names": _uniq(ticket_hints.service_names + log_signals.service_names),
        "environment_names": list(ticket_hints.environment_names),
        "file_paths": _uniq(ticket_hints.file_paths + log_signals.file_paths),
        "error_keywords": _uniq(ticket_hints.error_keywords + log_signals.error_keywords),
        "labels": list(ticket_hints.labels),
    }
    return DerivedSignalBundle(ticket_hints=ticket_hints, log_signals=log_signals, merged=merged)


def _signals_empty(signals: LogSignals) -> bool:
    return (
        not signals.severity_counts
        and not signals.repeated_error_lines
        and not signals.error_keywords
        and not signals.service_names
        and not signals.file_paths
        and not signals.stack_traces
        and not signals.time_window
    )


def _default_idempotency_key(ticket_key: str, log_content: str) -> str:
    digest = hashlib.sha256(log_content.encode("utf-8")).hexdigest()[:16]
    return f"jira-{ticket_key.lower()}-{digest}"


def _persist_investigation_trace(
    *,
    ticket: JiraNormalizedTicket,
    anomaly_id: str,
    run_id: str,
    run_status: str,
    bundle: DerivedSignalBundle,
    rca_view: dict[str, object],
) -> str:
    store = _get_investigation_store()
    payload: dict[str, object] = {
        "ticket_key": ticket.ticket_key,
        "ticket_id": ticket.ticket_id,
        "ticket_summary": ticket.summary,
        "ticket_status": ticket.status,
        "anomaly_id": anomaly_id,
        "run_id": run_id,
        "run_status": run_status,
        "rca_result_ref": {
            "latest_run_id": rca_view.get("latest_run_id"),
            "evidence_refs": rca_view.get("evidence_refs") or [],
        },
        "derived_signals_snapshot": {
            "ticket_hints": {
                "service_names": bundle.ticket_hints.service_names[:20],
                "environment_names": bundle.ticket_hints.environment_names[:20],
                "file_paths": bundle.ticket_hints.file_paths[:20],
                "error_keywords": bundle.ticket_hints.error_keywords[:20],
                "labels": bundle.ticket_hints.labels[:20],
            },
            "log_signals": {
                "severity_counts": dict(bundle.log_signals.severity_counts),
                "error_keywords": bundle.log_signals.error_keywords[:20],
                "service_names": bundle.log_signals.service_names[:20],
                "file_paths": bundle.log_signals.file_paths[:20],
                "stack_trace_count": len(bundle.log_signals.stack_traces),
                "time_window": bundle.log_signals.time_window,
            },
            "merged": {k: v[:20] for k, v in bundle.merged.items()},
        },
        "future_graph_links": {
            "ticket": ticket.ticket_key,
            "anomaly": anomaly_id,
            "services": bundle.merged.get("service_names", [])[:20],
            "files": bundle.merged.get("file_paths", [])[:20],
            "errors": bundle.merged.get("error_keywords", [])[:20],
        },
    }
    investigation_id = store.create_record(payload)
    deleted = _cleanup_old_investigations(store)
    logger.info(
        "jira_rca.persistence.saved investigation_id=%s ticket_key=%s cleanup_deleted=%d",
        investigation_id,
        ticket.ticket_key,
        deleted,
    )
    return investigation_id


def _get_investigation_store() -> LocalFileInvestigationStore:
    base = os.environ.get("JIRA_INVESTIGATION_STORE_DIR") or str(
        tempfile.gettempdir() + "/jira_rca_investigations"
    )
    return LocalFileInvestigationStore(base)


def _cleanup_old_investigations(store: LocalFileInvestigationStore) -> int:
    raw = (os.environ.get("JIRA_INVESTIGATION_RETENTION_DAYS") or "14").strip()
    try:
        days = int(raw)
    except ValueError:
        days = 14
    return store.cleanup_older_than(days)


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
