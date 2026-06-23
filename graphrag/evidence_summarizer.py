"""Summarize deterministic graph evidence into structured explanation bullets."""

from __future__ import annotations

from typing import Any, Optional


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_relative_minutes(minutes: Any) -> Optional[str]:
    m = _as_float(minutes)
    if m is None or m < 0:
        return None
    if m < 120:
        return f"{int(round(m))} minutes"
    hours = m / 60.0
    if hours < 48:
        return f"{int(round(hours))} hours"
    days = hours / 24.0
    return f"{int(round(days))} days"


def _signal_score(signals: list[dict[str, Any]], name: str) -> float:
    for s in signals:
        if s.get("name") == name:
            return _as_float(s.get("score")) or 0.0
    return 0.0


def _bullet(
    *,
    anomaly_id: str,
    candidate_rank: int,
    candidate_file_id: str,
    evidence_ref: str,
    category: str,
    text: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "anomaly_id": anomaly_id,
        "candidate_rank": candidate_rank,
        "candidate_file_id": candidate_file_id,
        "evidence_ref": evidence_ref,
        "category": category,
        "text": text,
        "evidence": evidence,
    }


def summarize_evidence(
    context_pack: dict[str, Any],
    *,
    max_bullets: int = 12,
) -> list[dict[str, Any]]:
    """
    Convert structured deterministic evidence into concise bullet objects.

    Facts are generated only from provided fields in `context_pack`.
    """
    anomaly_id = str(context_pack.get("anomaly_id") or "")
    candidates = context_pack.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return [
            _bullet(
                anomaly_id=anomaly_id,
                candidate_rank=0,
                candidate_file_id="",
                evidence_ref="",
                category="availability",
                text="No deterministic RCA candidates are available in the provided context.",
                evidence={},
            )
        ]

    ordered = sorted(
        (c for c in candidates if isinstance(c, dict)),
        key=lambda c: int(c.get("rank") or 10_000),
    )
    out: list[dict[str, Any]] = []

    for c in ordered:
        rank = int(c.get("rank") or 0)
        file_id = str(c.get("file_id") or "")
        path = str(c.get("path") or file_id or "unknown file")
        ref = str(c.get("evidence_ref") or "")
        conf = _as_float(c.get("confidence"))
        conf_text = f"{conf:.2f}" if conf is not None else "n/a"
        signals = c.get("signal_summary") or []
        cde = c.get("commit_deployment_evidence") or {}
        hre = c.get("historical_recurrence_evidence") or {}

        out.append(
            _bullet(
                anomaly_id=anomaly_id,
                candidate_rank=rank,
                candidate_file_id=file_id,
                evidence_ref=ref,
                category="candidate",
                text=f"Candidate rank {rank}: {path} (confidence {conf_text}).",
                evidence={
                    "path": path,
                    "confidence": conf,
                },
            )
        )

        # Top-frame/stack position indicator
        top_frame = _signal_score(signals, "top_frame")
        if top_frame >= 0.99:
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="stack",
                    text="This file appears in the top frame of the failure stack.",
                    evidence={"top_frame": top_frame},
                )
            )

        # Last-touch recency timing (only if explicit minutes/hours provided in evidence)
        last_touch_age = _format_relative_minutes(cde.get("last_touch_age_minutes"))
        if last_touch_age:
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="commit",
                    text=f"The file was modified approximately {last_touch_age} before the incident.",
                    evidence={
                        "last_touch_age_minutes": cde.get("last_touch_age_minutes"),
                        "last_touch_commit_sha": cde.get("last_touch_commit_sha") or "",
                    },
                )
            )
        elif cde.get("last_touch_commit_sha"):
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="commit",
                    text="A recent last-touch commit is linked to this file in the evidence bundle.",
                    evidence={
                        "last_touch_commit_sha": cde.get("last_touch_commit_sha") or "",
                    },
                )
            )

        # Deployment proximity timing (only with explicit age)
        deploy_age = _format_relative_minutes(cde.get("deployment_age_minutes"))
        dep_id = str(cde.get("deployment_id") or "")
        if dep_id and deploy_age:
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="deployment",
                    text=f"The relevant commit was deployed approximately {deploy_age} before the anomaly.",
                    evidence={
                        "deployment_id": dep_id,
                        "deployment_age_minutes": cde.get("deployment_age_minutes"),
                    },
                )
            )
        elif dep_id:
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="deployment",
                    text="A deployment linked to this file's commit exists in the RCA evidence.",
                    evidence={"deployment_id": dep_id},
                )
            )

        prior_count = int(hre.get("prior_count") or 0)
        if prior_count > 0:
            label = "incidents" if prior_count != 1 else "incident"
            out.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=rank,
                    candidate_file_id=file_id,
                    evidence_ref=ref,
                    category="recurrence",
                    text=f"This file has been accepted or attributed in {prior_count} prior {label}.",
                    evidence={
                        "prior_count": prior_count,
                        "normalized_score": _as_float(hre.get("normalized_score")),
                        "service_scope": hre.get("service_scope") or "",
                    },
                )
            )

        # Signal summary bullet (compact and reusable).
        if isinstance(signals, list) and signals:
            top = []
            for s in signals[:3]:
                name = str(s.get("name") or "")
                score = _as_float(s.get("score"))
                if not name or score is None:
                    continue
                top.append(f"{name}={score:.2f}")
            if top:
                out.append(
                    _bullet(
                        anomaly_id=anomaly_id,
                        candidate_rank=rank,
                        candidate_file_id=file_id,
                        evidence_ref=ref,
                        category="signals",
                        text=f"Top graph-derived signals: {', '.join(top)}.",
                        evidence={"top_signals": top},
                    )
                )

        if len(out) >= max_bullets:
            break

    out = _append_supplementary_context_bullets(
        context_pack,
        out,
        anomaly_id=anomaly_id,
        max_bullets=max_bullets,
    )

    return out[:max_bullets]


def _append_supplementary_context_bullets(
    context_pack: dict[str, Any],
    out: list[dict[str, Any]],
    *,
    anomaly_id: str,
    max_bullets: int,
) -> list[dict[str, Any]]:
    """Add Jira, feedback, similar-incident, and multi-agent bullets when present."""
    bullets = list(out)

    jira = context_pack.get("jira_ticket_context") or {}
    if isinstance(jira, dict) and jira.get("summary"):
        labels = ", ".join(str(label) for label in (jira.get("labels") or [])[:5])
        priority = str(jira.get("priority") or "n/a")
        status = str(jira.get("status") or "n/a")
        issue_key = str(jira.get("issue_key") or "ticket")
        bullets.append(
            _bullet(
                anomaly_id=anomaly_id,
                candidate_rank=0,
                candidate_file_id="",
                evidence_ref="",
                category="jira",
                text=(
                    f"Jira ticket {issue_key}: {jira.get('summary')} "
                    f"(priority {priority}, status {status}"
                    f"{', labels: ' + labels if labels else ''})."
                ),
                evidence={"ticket_context": jira},
            )
        )

    feedback = context_pack.get("feedback_context") or {}
    if isinstance(feedback, dict):
        for item in (feedback.get("confirmed_rcas") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="feedback",
                    text=(
                        "Historical Feedback (confirmed RCA): candidate "
                        f"{item.get('candidate_id')} — {_truncate_feedback_comment(item.get('comments'))}."
                    ),
                    evidence={"feedback": item},
                )
            )
        for item in (feedback.get("rejected_rcas") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="feedback",
                    text=(
                        "Historical Feedback (rejected RCA): candidate "
                        f"{item.get('candidate_id')} — {_truncate_feedback_comment(item.get('comments'))}."
                    ),
                    evidence={"feedback": item},
                )
            )
        for item in (feedback.get("overridden_rcas") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="feedback",
                    text=(
                        "Historical Feedback (overridden RCA): candidate "
                        f"{item.get('candidate_id')} -> {item.get('override_candidate_id')}."
                    ),
                    evidence={"feedback": item},
                )
            )

    similar = context_pack.get("similar_incident_context") or {}
    if isinstance(similar, dict):
        for item in (similar.get("previous_investigation_summaries") or [])[:2]:
            explanation = str(item.get("match_explanation") or "").strip()
            summary_text = explanation or (
                f"Historical incident {item.get('investigation_id')} "
                f"(score {item.get('similarity_score')}): "
                f"{item.get('resolution_summary') or 'prior investigation'}."
            )
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="similar_incident",
                    text=summary_text if summary_text.endswith(".") else f"{summary_text}.",
                    evidence={"similar_investigation": item},
                )
            )
        for item in (similar.get("historical_root_causes") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="similar_incident",
                    text=(
                        f"Historical root cause from {item.get('investigation_id')}: "
                        f"{item.get('root_cause')}."
                    ),
                    evidence={"historical_root_cause": item},
                )
            )
        for item in (similar.get("historical_feedback") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="feedback",
                    text=(
                        "Historical Feedback on similar incident "
                        f"{item.get('investigation_id')}: {item.get('feedback_type')} "
                        f"for candidate {item.get('candidate_id')}."
                    ),
                    evidence={"historical_feedback": item},
                )
            )
        for item in (similar.get("historical_remediation_actions") or [])[:2]:
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="similar_incident",
                    text=(
                        f"Historical remediation from {item.get('investigation_id')}: "
                        f"{item.get('action')}."
                    ),
                    evidence={"historical_remediation": item},
                )
            )

    multi_agent = context_pack.get("multi_agent_findings") or {}
    if isinstance(multi_agent, dict):
        if multi_agent.get("final_summary"):
            bullets.append(
                _bullet(
                    anomaly_id=anomaly_id,
                    candidate_rank=0,
                    candidate_file_id="",
                    evidence_ref="",
                    category="multi_agent",
                    text=f"Multi-Agent Findings: {multi_agent.get('final_summary')}",
                    evidence={"multi_agent_findings": multi_agent},
                )
            )
        for key in (
            "timeline_findings",
            "deployment_findings",
            "infrastructure_findings",
            "incident_findings",
            "knowledge_findings",
            "rca_findings",
        ):
            finding = multi_agent.get(key) or {}
            if isinstance(finding, dict) and finding.get("summary"):
                bullets.append(
                    _bullet(
                        anomaly_id=anomaly_id,
                        candidate_rank=0,
                        candidate_file_id="",
                        evidence_ref="",
                        category="multi_agent",
                        text=f"Multi-Agent {key.replace('_findings', '')}: {finding.get('summary')}",
                        evidence={"agent_finding": finding},
                    )
                )

    return bullets[:max_bullets]


def _truncate_feedback_comment(value: Any, limit: int = 120) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text or "no comment"
    return text[: limit - 3].rstrip() + "..."
