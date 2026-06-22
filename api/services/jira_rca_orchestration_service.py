"""
JIRA-first RCA orchestration: ticket + logs -> deterministic RCA entry.

Flow (single POST ``/api/v1/jira/rca/run``):

1. Resolve ticket via embedded ``ticket`` or fetch by ``ticket_key`` (``GET /api/v1/jira/tickets/{key}``).
2. Parse uploaded ``log_content`` into ``LogSignals``; merge with ticket hints into ``DerivedSignalBundle``.
3. Run existing deterministic RCA on ``anomaly_id`` (adapter: ``trigger_manual_rca``).
4. Load RCA result view, build grounded ``explanation_payload`` (assistive; RCA remains authoritative),
   ``relationship_bundle`` (graph-ready scaffold), and persist a minimal investigation JSON record.

Evidence bundle references appear only under ``rca.evidence_summary`` in the API response.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from artifacts.investigation_store import LocalFileInvestigationStore
from api.services.jira_service import fetch_ticket_context
from api.services.rca_service import get_rca_explanation, get_rca_result_view, trigger_manual_rca
from rca_engine.signal_computation import extract_keyword_signals, extract_signals
from schemas.jira import JiraExtractedHints, JiraNormalizedTicket
from schemas.jira_rca import (
    DerivedSignalBundle,
    JiraRcaExplanationPayload,
    JiraRcaResult,
    JiraRcaRunRequest,
    JiraRcaRunResponse,
    LogSignals,
    RelationshipReadyBundle,
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
_DASH_SERVICE_RE = re.compile(r"\b([a-z0-9][a-z0-9-]*-service)\b", re.IGNORECASE)
_ERROR_LINE_RE = re.compile(r"(?:\berror\b|\[error\]|level\s*=\s*error)", re.IGNORECASE)
_STACK_ERROR_RE = re.compile(r"error:", re.IGNORECASE)
_TRACE_FILE_RE = re.compile(r'File\s+["\']([^"\']+)["\']', re.IGNORECASE)
# Python traceback: File "path", line N — double or single quotes
_PY_FILE_LINE_RE = re.compile(
    r'File\s+["\']([^"\']+)["\']\s*,\s*line\s+\d+',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _jira_rca_debug_enabled() -> bool:
    return (os.environ.get("JIRA_RCA_DEBUG_LOG") or "").strip().lower() in {"1", "true", "yes", "on"}


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


@dataclass(frozen=True)
class RcaInputContext:
    """Unified RCA input contract for anomaly and JIRA/log modes."""

    mode: Literal["anomaly", "jira_log"]
    anomaly_id: str | None
    ticket: JiraNormalizedTicket
    ticket_hints: JiraExtractedHints
    log_signals: LogSignals
    merged_signals: dict[str, list[str]]
    log_content: str
    run_id: str
    force: bool


def run_jira_rca(request: JiraRcaRunRequest) -> JiraRcaRunResponse:
    """Execute deterministic RCA via anomaly or JIRA/log mode."""
    logger.info(
        "jira_rca.run.start anomaly_id=%s ticket_key=%s",
        (request.anomaly_id or "").strip(),
        (request.ticket_key or (request.ticket.ticket_key if request.ticket else "")),
    )
    ticket, ticket_hints = _resolve_ticket_context(request)
    raw_log = request.log_content or ""
    if _jira_rca_debug_enabled() or logger.isEnabledFor(logging.DEBUG):
        snippet = raw_log[:200].replace("\n", "\\n").replace("\r", "\\r")
        logger.info(
            "jira_rca.log_content len=%d snippet=%s",
            len(raw_log),
            snippet,
        )
    log_signals = _derive_log_signals(raw_log)
    if _jira_rca_debug_enabled():
        logger.info(
            "jira_rca.signals.structure severity=%s repeated=%s keywords=%s services=%s paths=%d stacks=%d",
            dict(log_signals.severity_counts),
            log_signals.repeated_error_lines[:3],
            log_signals.error_keywords[:10],
            log_signals.service_names[:10],
            len(log_signals.file_paths),
            len(log_signals.stack_traces),
        )
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

    ticket_hints = _maybe_enrich_hints_via_mcp(
        ticket=ticket,
        ticket_hints=ticket_hints,
        log_signals=log_signals,
    )

    bundle = _merge_signals(ticket_hints, log_signals)
    anomaly_id = (request.anomaly_id or "").strip() or None
    run_id = request.idempotency_key or _default_idempotency_key(ticket.ticket_key, request.log_content)
    rca_input = RcaInputContext(
        mode="anomaly" if anomaly_id else "jira_log",
        anomaly_id=anomaly_id,
        ticket=ticket,
        ticket_hints=ticket_hints,
        log_signals=log_signals,
        merged_signals=bundle.merged,
        log_content=request.log_content,
        run_id=run_id,
        force=request.force,
    )

    logger.info(
        "jira_rca.engine.invoke mode=%s anomaly_id=%s run_id=%s force=%s",
        rca_input.mode,
        anomaly_id,
        run_id,
        request.force,
    )
    rca_run = _run_deterministic_rca_for_input(rca_input)
    run_status = str(rca_run.get("status") or "")
    if run_status in {"blocked", "rejected"}:
        logger.warning(
            "jira_rca.engine.blocked anomaly_id=%s run_id=%s status=%s",
            anomaly_id,
            run_id,
            run_status,
        )
        raise RcaUnableToRankCandidateError(str(rca_run.get("reason") or "rca run blocked"))

    rca_view = dict(rca_run.get("rca_view") or {})
    if not rca_view and anomaly_id:
        rca_view = get_rca_result_view(anomaly_id)
    accepted = rca_view.get("accepted_root_cause")
    candidates = rca_view.get("candidate_root_causes") or []
    if not accepted and not candidates:
        logger.warning("jira_rca.engine.no_candidates anomaly_id=%s run_id=%s", anomaly_id, run_id)
        raise RcaUnableToRankCandidateError("RCA unable to rank candidate for anomaly")

    evidence_summary = _build_evidence_summary(
        rca_view=rca_view,
        log_signals=log_signals,
        run_id=str(rca_run.get("run_id") or run_id),
    )
    relationship_bundle = _build_relationship_bundle(
        ticket=ticket,
        anomaly_id=anomaly_id,
        ticket_hints=ticket_hints,
        log_signals=log_signals,
        rca_view=rca_view,
    )
    investigation_id = _persist_investigation_trace(
        ticket=ticket,
        anomaly_id=anomaly_id,
        run_id=str(rca_run.get("run_id") or run_id),
        run_status=run_status or "completed",
        bundle=bundle,
        rca_view=rca_view,
        relationship_bundle=relationship_bundle,
    )
    evidence_summary["investigation_id"] = investigation_id
    logger.info(
        "jira_rca.run.success anomaly_id=%s run_id=%s investigation_id=%s",
        anomaly_id,
        str(rca_run.get("run_id") or run_id),
        investigation_id,
    )
    explanation_payload = _build_explanation_payload(
        anomaly_id=anomaly_id,
        ticket=ticket,
        ticket_hints=ticket_hints,
        log_signals=log_signals,
        rca_view=rca_view,
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
        explanation_payload=explanation_payload,
        relationship_bundle=relationship_bundle,
    )


def _run_deterministic_rca_for_input(ctx: RcaInputContext) -> dict[str, object]:
    """Explicit RCA mode switch: anomaly-first or JIRA/log-first."""
    if ctx.mode == "anomaly":
        assert ctx.anomaly_id is not None
        run = trigger_manual_rca(ctx.anomaly_id, ctx.run_id, force=ctx.force)
        if str(run.get("status") or "") == "completed":
            run["rca_view"] = get_rca_result_view(ctx.anomaly_id)
        return run
    return _run_jira_log_deterministic_rca(ctx)


def _run_jira_log_deterministic_rca(ctx: RcaInputContext) -> dict[str, object]:
    """Deterministic RCA path from ticket/log-derived signals without anomaly_id."""
    keyword_signals = extract_keyword_signals(ctx.log_content or "")
    candidates = _rank_jira_log_candidates(
        log_signals=ctx.log_signals,
        ticket_hints=ctx.ticket_hints,
        file_paths=ctx.merged_signals.get("file_paths", []),
        log_content=ctx.log_content,
        run_id=ctx.run_id,
    )
    if not candidates:
        fallback = _build_log_keyword_fallback_candidates(
            keyword_signals=keyword_signals,
            run_id=ctx.run_id,
        )
        candidates = fallback

    primary_cause = _build_primary_cause_text(keyword_signals)
    confidence_label = "MEDIUM"
    return {
        "status": "completed",
        "run_id": ctx.run_id,
        "rca_view": {
            "anomaly_id": None,
            "current_status": "has_candidates",
            "accepted_root_cause": None,
            "candidate_root_causes": candidates,
            "latest_run_id": ctx.run_id,
            "evidence_refs": [],
            "last_updated_at": None,
            "mode": "jira_log",
            "primary_cause": primary_cause,
            "confidence": confidence_label,
            "signals": keyword_signals,
        },
    }


def _rank_jira_log_candidates(
    *,
    log_signals: LogSignals,
    ticket_hints: JiraExtractedHints,
    file_paths: list[str],
    log_content: str,
    run_id: str,
) -> list[dict[str, object]]:
    """Rank candidate file paths from deterministic log evidence."""
    unique_paths = _uniq([p for p in file_paths if p])
    if not unique_paths:
        return []
    stack_lines: list[str] = []
    for block in log_signals.stack_traces:
        stack_lines.extend([ln for ln in block.splitlines() if ln.strip()])
    repeated_lines = [ln for ln in log_signals.repeated_error_lines if ln.strip()]
    lines = stack_lines + repeated_lines
    # If stack/repeat lines are empty (e.g. traceback parse missed quotes, or single ERROR line),
    # fall back to all non-empty lines so path mentions still score deterministically.
    if not lines:
        lines = [ln.strip() for ln in (log_content or "").splitlines() if ln.strip()]

    trace_paths_ordered = _extract_python_trace_paths_ordered(log_content or "")
    trace_index = {p: i for i, p in enumerate(trace_paths_ordered)}
    last_trace_path = trace_paths_ordered[-1] if trace_paths_ordered else None
    has_timeout_error = bool(re.search(r"\btimeouterror\b", log_content or "", re.IGNORECASE))

    ticket_services = {svc.lower() for svc in ticket_hints.service_names}
    log_services = {svc.lower() for svc in log_signals.service_names}
    merged_services = ticket_services | log_services

    scored: list[tuple[str, float, dict[str, float]]] = []
    for path in unique_paths:
        mentions = sum(1 for ln in lines if path in ln)
        stack_mentions = sum(1 for ln in stack_lines if path in ln)
        repeated_mentions = sum(1 for ln in repeated_lines if path in ln)
        keyword_hits = sum(
            1
            for ln in lines
            for kw in log_signals.error_keywords
            if kw and path in ln and kw.lower() in ln.lower()
        )
        has_error_level = any(
            path in ln and (_LEVEL_PATTERNS["error"].search(ln) or _LEVEL_PATTERNS["critical"].search(ln))
            for ln in lines
        )
        service_alignment = any(svc in path.lower() for svc in merged_services if svc)
        # Prefer later traceback frames (often closer to the thrown error) deterministically.
        trace_depth_bonus = 0.0
        if trace_paths_ordered and path in trace_index:
            trace_depth_bonus = (trace_index[path] + 1) / max(len(trace_paths_ordered), 1)
        last_frame_bonus = 1.0 if last_trace_path and path == last_trace_path else 0.0
        if mentions == 0:
            continue
        signals = {
            "path_mentions": min(1.0, mentions / 6.0),
            "stack_path_mentions": min(1.0, stack_mentions / 4.0),
            "repeated_error_alignment": min(1.0, repeated_mentions / 3.0),
            "keyword_hits": min(1.0, keyword_hits / 4.0),
            "error_level_alignment": 1.0 if has_error_level else 0.0,
            "service_alignment": 1.0 if service_alignment else 0.0,
            "trace_depth_bonus": round(trace_depth_bonus, 4),
            "last_trace_frame": last_frame_bonus,
        }
        exception_raising_frame_bonus = 1.0 if (has_timeout_error and last_frame_bonus > 0.0) else 0.0
        score = (
            (0.26 * signals["path_mentions"])
            + (0.16 * signals["stack_path_mentions"])
            + (0.12 * signals["repeated_error_alignment"])
            + (0.12 * signals["keyword_hits"])
            + (0.08 * signals["error_level_alignment"])
            + (0.05 * signals["service_alignment"])
            + (0.08 * trace_depth_bonus)
            + (0.13 * last_frame_bonus)
            + (0.12 * exception_raising_frame_bonus)
        )
        signals["exception_raising_frame"] = exception_raising_frame_bonus
        scored.append((path, score, signals))

    scored.sort(key=lambda item: (-item[1], item[0]))
    top = scored[:3]
    if not top:
        return []

    max_score = max(item[1] for item in top) or 1.0
    out: list[dict[str, object]] = []
    for idx, (path, score, signals) in enumerate(top):
        confidence = round(min(0.99, score / max_score), 4)
        stack_evidence = next((ln for ln in stack_lines if path in ln), "")
        out.append(
            {
                "file_id": f"jira-log:{hashlib.sha1(path.encode('utf-8')).hexdigest()[:12]}",
                "path": path,
                "confidence": confidence,
                "run_id": run_id,
                "evidence_ref": None,
                "rank": idx + 1,
                "signal_scores": signals,
                "stack_evidence": stack_evidence,
            }
        )
    return out


def _build_log_keyword_fallback_candidates(
    *,
    keyword_signals: dict[str, object],
    run_id: str,
) -> list[dict[str, object]]:
    """Fallback candidate generation when no file-path candidates can be ranked."""
    service = str(keyword_signals.get("service") or "").strip() or "unknown-service"
    reason_bits: list[str] = []
    if int(keyword_signals.get("error_count") or 0) > 0:
        reason_bits.append("High error rate")
    if int(keyword_signals.get("timeout") or 0) > 0:
        reason_bits.append("timeout pattern")
    reason = " + ".join(reason_bits) if reason_bits else "log keyword anomaly pattern"
    return [
        {
            "service": service,
            "reason": reason,
            "path": f"service::{service}",
            "file_id": f"jira-log:fallback:{service}",
            "confidence": 0.6,
            "run_id": run_id,
            "evidence_ref": None,
            "rank": 1,
            "signal_scores": {
                "error_count": int(keyword_signals.get("error_count") or 0),
                "timeout": int(keyword_signals.get("timeout") or 0),
            },
            "stack_evidence": "",
        }
    ]


def _build_primary_cause_text(keyword_signals: dict[str, object]) -> str:
    """Human-readable forced RCA output when stack traces are unavailable."""
    service = str(keyword_signals.get("service") or "").strip() or "unknown-service"
    timeout_count = int(keyword_signals.get("timeout") or 0)
    if timeout_count > 0:
        return f"High timeout errors detected in {service}"
    if int(keyword_signals.get("error_count") or 0) > 0:
        return f"High error volume detected in {service}"
    return f"Anomalous log keyword pattern detected in {service}"


def _extract_python_trace_paths_ordered(content: str) -> list[str]:
    """Paths from Python tracebacks in source order (deduped, stable)."""
    found = _PY_FILE_LINE_RE.findall(content or "")
    out: list[str] = []
    seen: set[str] = set()
    for p in found:
        p = (p or "").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _maybe_enrich_hints_via_mcp(
    *,
    ticket: JiraNormalizedTicket,
    ticket_hints: JiraExtractedHints,
    log_signals: LogSignals,
) -> JiraExtractedHints:
    """
    Optionally fetch MCP investigation context and enrich ticket hints.

    When ``MCP_ENABLED=false`` this is a no-op — existing RCA behavior is unchanged.
    """
    try:
        from mcp.config import MCPFetchParams, default_enabled_sources, mcp_enabled
        from mcp.context.context_builder import enrich_ticket_hints
        from mcp.orchestrator import MCPOrchestrator
    except ImportError:
        return ticket_hints

    if not mcp_enabled():
        return ticket_hints

    tw = log_signals.time_window or {}
    service = ""
    if ticket_hints.service_names:
        service = ticket_hints.service_names[0]

    params = MCPFetchParams(
        ticket_key=ticket.ticket_key,
        service_name=service,
        repo_name="",
        start_time=tw.get("start"),
        end_time=tw.get("end"),
        enabled_sources=default_enabled_sources(),
    )
    try:
        context = MCPOrchestrator().fetch_context(params)
        enriched = enrich_ticket_hints(ticket_hints, context)
        logger.info(
            "jira_rca.mcp.enriched ticket_key=%s sources=%d commits=%d prs=%d",
            ticket.ticket_key,
            len(context.source_metadata),
            len(context.commits),
            len(context.pull_requests),
        )
        return enriched
    except Exception as exc:
        logger.warning("jira_rca.mcp.enrich_failed ticket_key=%s err=%s", ticket.ticket_key, exc)
        return ticket_hints


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
    # Strip BOM / odd whitespace that can hide ERROR tokens from parsers
    if content.startswith("\ufeff"):
        content = content.lstrip("\ufeff").strip()
    if not content:
        logger.warning("jira_rca.logs.empty")
        raise EmptyLogContentError("empty log file/content")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]

    severity_counts: dict[str, int] = {}
    for level, pattern in _LEVEL_PATTERNS.items():
        count = sum(1 for ln in lines if pattern.search(ln))
        if count > 0:
            severity_counts[level] = count
    # Explicit required ERROR detections: ERROR / [ERROR] / level=error (case-insensitive).
    error_lines = [ln for ln in lines if _ERROR_LINE_RE.search(ln)]
    if error_lines:
        severity_counts["error"] = max(severity_counts.get("error", 0), len(error_lines))

    err_lines = [ln for ln in lines if _LEVEL_PATTERNS["error"].search(ln) or _LEVEL_PATTERNS["critical"].search(ln)]
    if not err_lines:
        err_lines = list(error_lines)
    normalized_err_lines = [_normalize_error_line_for_repeat_detection(ln) for ln in err_lines]
    repeated_error_lines = [txt for txt, n in Counter(normalized_err_lines).items() if n > 1]

    lower_blob = content.lower()
    keyword_bank = ["timeout", "error", "failed", "invalid", "exception"]
    error_keywords = _uniq([k for k in keyword_bank if k in lower_blob])
    service_names = _uniq(
        [m.lower() for m in _DASH_SERVICE_RE.findall(content)]
        + [m.lower() for m in _SERVICE_RE.findall(content)]
    )
    file_paths = _uniq(
        _UNIX_PATH_RE.findall(content)
        + _WIN_PATH_RE.findall(content)
        + _TRACE_FILE_RE.findall(content)
        + _extract_python_trace_paths_ordered(content)
    )

    stack_blocks = _extract_stack_traces(lines)
    signals = extract_signals(log_content)
    fallback_signals = signals
    time_window = _extract_time_window(content)
    # Do not return effectively empty signals when explicit ERROR lines exist.
    if error_lines and not error_keywords:
        error_keywords = ["error"]
    if error_lines and not stack_blocks:
        stack_like = [ln for ln in lines if ln.startswith("Traceback") or _STACK_ERROR_RE.search(ln)]
        if stack_like:
            stack_blocks = ["\n".join(stack_like[:20])]
    if error_lines and not severity_counts.get("error"):
        severity_counts["error"] = len(error_lines)

    # Mandatory fallback path: when no stack traces are present, still extract deterministic
    # signals directly from raw log lines.
    if not stack_blocks:
        if int(fallback_signals.get("error_count") or 0) > 0:
            severity_counts["error"] = max(
                severity_counts.get("error", 0),
                int(fallback_signals.get("error_count") or 0),
            )
        if int(fallback_signals.get("timeout_count") or 0) > 0 and "timeout" not in error_keywords:
            error_keywords.append("timeout")
        if int(fallback_signals.get("invalid_token_count") or 0) > 0 and "invalid token" not in error_keywords:
            error_keywords.append("invalid token")
        svc = str(fallback_signals.get("service") or "").strip().lower()
        if svc and svc not in service_names:
            service_names.append(svc)
        fallback_patterns = [p for p in (fallback_signals.get("patterns") or []) if isinstance(p, str)]
        if fallback_patterns and not repeated_error_lines:
            repeated_error_lines = fallback_patterns[:20]

    signals = LogSignals(
        severity_counts=severity_counts,
        repeated_error_lines=repeated_error_lines[:20],
        error_keywords=error_keywords,
        service_names=service_names,
        file_paths=file_paths[:100],
        stack_traces=stack_blocks[:5],
        time_window=time_window,
    )
    return signals


def _extract_stack_traces(lines: list[str]) -> list[str]:
    traces: list[str] = []
    current: list[str] = []
    _file_line_re = re.compile(r'File\s+["\'].+["\']\s*,\s*line\s+\d+', re.IGNORECASE)
    for ln in lines:
        looks_like_stack = (
            ln.startswith("Traceback")
            or ln.startswith("at ")
            or bool(_file_line_re.search(ln))
            or bool(_STACK_ERROR_RE.search(ln))
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


def _normalize_error_line_for_repeat_detection(line: str) -> str:
    """Normalize volatile tokens (timestamps) to detect semantic repeats."""
    out = _TS_RE.sub("<ts>", line or "")
    out = re.sub(r"\s+", " ", out).strip()
    return out


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
    anomaly_id: str | None,
    run_id: str,
    run_status: str,
    bundle: DerivedSignalBundle,
    rca_view: dict[str, object],
    relationship_bundle: RelationshipReadyBundle,
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
            "anomaly": anomaly_id or "",
            "services": bundle.merged.get("service_names", [])[:20],
            "files": bundle.merged.get("file_paths", [])[:20],
            "errors": bundle.merged.get("error_keywords", [])[:20],
        },
        "relationship_ready_bundle": relationship_bundle.model_dump(),
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


def _classify_assist_status(expl: dict[str, object]) -> Literal["ok", "partial", "unavailable"]:
    """Whether GraphRAG assistive explanation succeeded (deterministic RCA still authoritative)."""
    if not expl:
        return "unavailable"
    summary = str(expl.get("explanation_summary") or "")
    limitations = str(expl.get("limitations") or "")
    low_sum = summary.lower()
    if "explanation unavailable" in low_sum or "internal error" in low_sum:
        return "partial"
    if limitations.strip():
        return "partial"
    if summary.strip():
        return "ok"
    return "partial"


def _build_explanation_payload(
    *,
    anomaly_id: str | None,
    ticket: JiraNormalizedTicket,
    ticket_hints: JiraExtractedHints,
    log_signals: LogSignals,
    rca_view: dict[str, object],
) -> JiraRcaExplanationPayload:
    root = _select_root_cause(rca_view)
    confidence = float(root.get("confidence") or 0.0)
    expl = _safe_get_rca_explanation(anomaly_id)
    assist_status = _classify_assist_status(expl)
    jira_log_mode = rca_view.get("mode") == "jira_log"

    base_explanation = str(expl.get("explanation_summary") or "").strip()
    if not base_explanation:
        if jira_log_mode:
            base_explanation = (
                "Deterministic JIRA/log RCA ranked file-path candidates from uploaded logs using "
                "stack traces, repeated errors, keyword/path co-occurrence, and traceback depth. "
                "JIRA text is contextual only; log-derived signals are authoritative."
            )
        else:
            base_explanation = (
                "Deterministic RCA selected the top candidate from graph evidence. "
                "Explanation detail is limited because assistive explanation text is unavailable."
            )
    confidence_note = str(expl.get("confidence_alignment_note") or "").strip()
    if not confidence_note:
        confidence_note = (
            "Deterministic RCA ranking remains authoritative; contextual explanation is assistive only."
        )
    if confidence < 0.5:
        confidence_note += " Confidence is moderate/low, so validate with additional checks before applying fixes."
    if jira_log_mode and assist_status == "unavailable":
        assist_status = "partial"

    remediation_suggestions = _build_remediation_suggestions(
        root=root,
        log_signals=log_signals,
        expl=expl,
        confidence=confidence,
        jira_log_mode=jira_log_mode,
    )
    explanation = _compose_grounded_explanation(
        ticket=ticket,
        root=root,
        base_explanation=base_explanation,
        confidence=confidence,
    )
    return JiraRcaExplanationPayload(
        root_cause=root,
        assist_status=assist_status,
        ticket_context_summary={
            "ticket_key": ticket.ticket_key,
            "summary": ticket.summary,
            "status": ticket.status,
            "priority": ticket.priority,
            "labels": ticket.labels,
            "service_names": ticket_hints.service_names,
            "environment_names": ticket_hints.environment_names,
        },
        log_signal_summary={
            "severity_counts": dict(log_signals.severity_counts),
            "error_keywords": log_signals.error_keywords,
            "service_names": log_signals.service_names,
            "repeated_error_lines_count": len(log_signals.repeated_error_lines),
            "stack_trace_count": len(log_signals.stack_traces),
            "time_window": log_signals.time_window,
        },
        explanation=explanation,
        remediation_suggestions=remediation_suggestions,
        confidence_note=confidence_note,
    )


def _safe_get_rca_explanation(anomaly_id: str | None) -> dict[str, object]:
    if not anomaly_id:
        return {}
    try:
        out = get_rca_explanation(anomaly_id)
        if isinstance(out, dict):
            return out
    except Exception as exc:
        logger.warning("jira_rca.explanation.fallback anomaly_id=%s error=%s", anomaly_id, str(exc))
    return {}


def _select_root_cause(rca_view: dict[str, object]) -> dict[str, object]:
    accepted = rca_view.get("accepted_root_cause")
    if isinstance(accepted, dict) and accepted:
        return {
            "source": "accepted_root_cause",
            "file_id": accepted.get("file_id"),
            "path": accepted.get("path"),
            "confidence": float(accepted.get("confidence") or 0.0),
            "run_id": accepted.get("run_id"),
            "evidence_ref": accepted.get("evidence_ref"),
        }
    candidates = rca_view.get("candidate_root_causes")
    if isinstance(candidates, list) and candidates:
        top = candidates[0] if isinstance(candidates[0], dict) else {}
        return {
            "source": "top_ranked_candidate",
            "file_id": top.get("file_id"),
            "path": top.get("path"),
            "confidence": float(top.get("confidence") or 0.0),
            "run_id": top.get("run_id"),
            "evidence_ref": top.get("evidence_ref"),
            "stack_evidence": top.get("stack_evidence"),
        }
    return {"source": "unavailable", "confidence": 0.0}


def _compose_grounded_explanation(
    *,
    ticket: JiraNormalizedTicket,
    root: dict[str, object],
    base_explanation: str,
    confidence: float,
) -> str:
    target = str(root.get("path") or root.get("file_id") or "unknown target")
    stack_evidence = ""
    if isinstance(root.get("stack_evidence"), str) and str(root.get("stack_evidence")).strip():
        stack_evidence = f" Stack evidence: {str(root.get('stack_evidence')).strip()}."
    return (
        f"Ticket {ticket.ticket_key} context and uploaded log signals were processed, then deterministic RCA ranked "
        f"{target} as the leading root-cause candidate (confidence {confidence:.2f}). {base_explanation}{stack_evidence}"
    ).strip()


def _build_remediation_suggestions(
    *,
    root: dict[str, object],
    log_signals: LogSignals,
    expl: dict[str, object],
    confidence: float,
    jira_log_mode: bool = False,
) -> list[str]:
    target = str(root.get("path") or root.get("file_id") or "top candidate file")
    out = [
        "Validate the candidate against latest deployment/change history before code changes.",
        f"Inspect `{target}` around failing execution paths and compare with recent regressions.",
        "Apply reversible mitigation first (feature flag, timeout guard, retry tuning), then monitor error rate.",
    ]
    if jira_log_mode:
        if any(k in log_signals.error_keywords for k in ("timeout", "otp")):
            out.append(
                "Review OTP/MFA timeout budgets, downstream dependency latency, and retry semantics in the ranked path."
            )
        if log_signals.stack_traces:
            out.append("Use the traceback frames above to narrow the failing call chain before changing behavior.")
    if log_signals.time_window:
        out.append(
            "Correlate candidate behavior with the observed log time window to confirm temporal alignment."
        )
    patch_hint = str(expl.get("optional_patch_direction") or "").strip()
    if patch_hint:
        out.append(f"Advisory patch direction: {patch_hint}")
    if confidence < 0.5:
        out.append("Because confidence is not strong, treat this as a hypothesis and validate multiple candidates.")
    return out[:6]


def _build_relationship_bundle(
    *,
    ticket: JiraNormalizedTicket,
    anomaly_id: str | None,
    ticket_hints: JiraExtractedHints,
    log_signals: LogSignals,
    rca_view: dict[str, object],
) -> RelationshipReadyBundle:
    root = _select_root_cause(rca_view)
    root_file = str(root.get("path") or root.get("file_id") or "")
    services = _uniq(ticket_hints.service_names + log_signals.service_names)[:30]
    errors = _uniq(ticket_hints.error_keywords + log_signals.error_keywords)[:40]
    file_paths = _uniq(ticket_hints.file_paths + log_signals.file_paths)[:50]
    if root_file and root_file not in file_paths:
        file_paths = [root_file] + file_paths

    return RelationshipReadyBundle(
        ticket_key=ticket.ticket_key,
        anomaly_id=anomaly_id,
        rca_target_file=root_file or None,
        candidate_services=services,
        candidate_errors=errors,
        candidate_file_paths=file_paths,
        entity_refs={
            "ticket": [ticket.ticket_key],
            "anomaly": [anomaly_id] if anomaly_id else [],
            "service": services,
            "error": errors,
            "file": file_paths,
        },
    )


def _build_evidence_summary(
    *,
    rca_view: dict[str, object],
    log_signals: LogSignals,
    run_id: str,
) -> dict[str, object]:
    evidence_refs = rca_view.get("evidence_refs") or []
    highlights: list[str] = []
    if log_signals.repeated_error_lines:
        highlights.append(f"Repeated error lines detected: {len(log_signals.repeated_error_lines)}")
    if log_signals.service_names:
        highlights.append(f"Services seen in logs: {', '.join(log_signals.service_names[:3])}")
    if log_signals.file_paths:
        highlights.append(f"File paths observed: {', '.join(log_signals.file_paths[:2])}")
    if log_signals.error_keywords:
        highlights.append(f"Error keywords: {', '.join(log_signals.error_keywords[:6])}")
    if log_signals.stack_traces:
        first_stack_line = next(
            (ln.strip() for ln in log_signals.stack_traces[0].splitlines() if ln.strip()),
            "",
        )
        if first_stack_line:
            highlights.append(f"Stack trace present: {first_stack_line[:180]}")
    return {
        "bundle_count": len(evidence_refs),
        "evidence_refs": evidence_refs,
        "latest_run_id": rca_view.get("latest_run_id") or run_id,
        "evidence_highlights": highlights,
    }


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
