"""Build concise, guardrailed prompts for graph-grounded RCA explanations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

MINIMAL_DETERMINISTIC_SYSTEM_PROMPT = (
    "You are an incident RCA explanation assistant. The deterministic RCA engine has already "
    "selected the authoritative root-cause candidate. Your task is to explain that result using "
    "only the supplied evidence. You must not replace, rerank, or contradict the selected "
    "candidate. Distinguish observed evidence from reasonable interpretation. Do not invent "
    "technical details, files, services, commits, deployments, tickets, functions, or historical "
    "incidents that are not present in the supplied context. "
    "Write a professional, evidence-grounded explanation_summary of approximately 180-300 words "
    "in 2-4 readable paragraphs of plain text (no Markdown headings, no remediation bullets, "
    "no JSON inside explanation_summary). Cover: (1) incident context from ticket/logs/stack "
    "without overemphasizing missing ticket data; (2) the selected candidate with normalized "
    "path/component and deterministic confidence when provided; (3) why it ranked first using "
    "the strongest 2-4 available signals in natural language; (4) a grounded interpretation of "
    "what likely happened, clearly labeled as interpretation where needed; (5) relevant "
    "uncertainty or missing evidence without fabricating facts. "
    "Keep remediation out of explanation_summary. "
    "Output strict JSON only, with exactly these keys and no others: "
    "explanation_summary, evidence_highlights, confidence_alignment_note, optional_patch_direction, limitations. "
    "evidence_highlights must be a list of strings copied verbatim from the SUPPORTING SIGNALS / "
    "evidence highlight lines in the user prompt, or short paraphrases that add no new facts. "
    "optional_patch_direction must be advisory (use words like advisory, consider, or suggest). "
    "If context is insufficient, say so in limitations and in the uncertainty portion of the summary."
)


SYSTEM_PROMPT = (
    "You are an RCA explanation assistant. Use only the provided deterministic graph context. "
    "Do not invent files, candidates, commits, deployments, or evidence. "
    "Do not re-rank candidates; deterministic ranking is the source of truth. "
    "Explain why the top candidate is most likely, summarize top-3 ranked hypotheses, "
    "align reasoning with provided confidence values, and provide optional advisory-only patch direction. "
    "If evidence is incomplete, explicitly state uncertainty. "
    "Output must be strict JSON only."
)


def _extract_ranked_candidates(context_pack: Mapping[str, Any], max_candidates: int) -> list[dict[str, Any]]:
    raw = context_pack.get("candidates") or []
    if not isinstance(raw, list):
        return []
    ranked = [c for c in raw if isinstance(c, Mapping)]
    ranked.sort(key=lambda c: int(c.get("rank") or 10_000))
    out: list[dict[str, Any]] = []
    for c in ranked[:max_candidates]:
        out.append(
            {
                "rank": c.get("rank"),
                "file_id": c.get("file_id"),
                "path": c.get("path"),
                "confidence": c.get("confidence"),
                "evidence_ref": c.get("evidence_ref"),
            }
        )
    return out


def build_prompt(
    context_pack: Mapping[str, Any],
    summarized_evidence: list[Mapping[str, Any]] | list[str],
    *,
    user_instruction: Optional[str] = None,
    max_hypotheses: int = 3,
) -> dict[str, str]:
    """
    Build system/user prompt strings for LLM explanation generation.

    Prompt objectives:
    - explain top deterministic candidate
    - summarize top-3 ranked hypotheses (without re-ranking)
    - provide confidence-aligned reasoning
    - include optional advisory-only patch direction
    """
    instruction = user_instruction or (
        "Explain the deterministic RCA outcome using only provided evidence."
    )
    ranked_candidates = _extract_ranked_candidates(context_pack, max_hypotheses)
    primary = ranked_candidates[0] if ranked_candidates else {}
    payload = {
        "task": instruction,
        "rules": {
            "must_not_rerank": True,
            "must_not_introduce_new_candidates": True,
            "deterministic_ranking_source_of_truth": True,
            "patch_direction_must_be_advisory": True,
            "no_full_proprietary_code_or_raw_logs": True,
        },
        "required_response_fields": [
            "anomaly_id",
            "primary_candidate",
            "ranked_hypotheses",
            "explanation_summary",
            "evidence_highlights",
            "confidence_alignment_note",
            "optional_patch_direction",
            "limitations",
        ],
        "response_constraints": {
            "ranked_hypotheses_max": max_hypotheses,
            "ranked_hypotheses_must_match_input_order": True,
            "json_only": True,
        },
        "context": {
            "anomaly_id": context_pack.get("anomaly_id"),
            "trace_ref": context_pack.get("trace_ref"),
            "run_id": context_pack.get("run_id"),
            "top_ranked_candidates": ranked_candidates,
            "primary_candidate_hint": primary,
            "packed_context": context_pack,
            "summarized_evidence": summarized_evidence,
        },
    }
    return {
        "system": SYSTEM_PROMPT,
        "user": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
    }


def _evidence_bullet_strings(summarized_evidence: list[Mapping[str, Any]] | list[str]) -> list[str]:
    out: list[str] = []
    for item in summarized_evidence:
        if isinstance(item, Mapping):
            t = item.get("text")
        elif isinstance(item, str):
            t = item
        else:
            t = None
        if isinstance(t, str) and t.strip() and t not in out:
            out.append(t)
    return out


def _bullets_by_category(
    summarized_evidence: list[Mapping[str, Any]] | list[str],
    categories: set[str],
) -> list[str]:
    out: list[str] = []
    for item in summarized_evidence:
        if not isinstance(item, Mapping):
            continue
        cat = str(item.get("category") or "").strip().lower()
        if cat not in categories:
            continue
        t = item.get("text")
        if isinstance(t, str) and t.strip() and t not in out:
            out.append(t)
    return out


def _historical_feedback_lines(context_pack: Mapping[str, Any], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    feedback = context_pack.get("feedback_context") or {}
    if isinstance(feedback, dict):
        for item in feedback.get("confirmed_rcas") or []:
            lines.append(
                f"Confirmed RCA for candidate {item.get('candidate_id')}: {item.get('comments') or 'no comment'}"
            )
        for item in feedback.get("rejected_rcas") or []:
            lines.append(
                f"Rejected RCA for candidate {item.get('candidate_id')}: {item.get('comments') or 'no comment'}"
            )
        for item in feedback.get("overridden_rcas") or []:
            lines.append(
                "Overridden RCA "
                f"{item.get('candidate_id')} -> {item.get('override_candidate_id')}: "
                f"{item.get('comments') or 'no comment'}"
            )

    similar = context_pack.get("similar_incident_context") or {}
    if isinstance(similar, dict):
        for item in similar.get("historical_feedback") or []:
            lines.append(
                "Historical Feedback on similar incident "
                f"{item.get('investigation_id')}: {item.get('feedback_type')} "
                f"candidate {item.get('candidate_id')}"
            )

    deduped: list[str] = []
    for line in lines:
        text = str(line).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:limit]


def _historical_incident_lines(context_pack: Mapping[str, Any], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    similar = context_pack.get("similar_incident_context") or {}
    if not isinstance(similar, dict):
        return lines

    for item in similar.get("previous_investigation_summaries") or []:
        explanation = str(item.get("match_explanation") or "").strip()
        if explanation:
            lines.append(explanation)
        else:
            lines.append(
                "Historical incident "
                f"{item.get('investigation_id')} (score {item.get('similarity_score')}): "
                f"{item.get('resolution_summary') or 'prior investigation'}"
            )
    for item in similar.get("historical_root_causes") or []:
        lines.append(
            f"Historical root cause from {item.get('investigation_id')}: {item.get('root_cause')}"
        )
    for item in similar.get("historical_remediation_actions") or []:
        lines.append(
            f"Historical remediation from {item.get('investigation_id')}: {item.get('action')}"
        )

    # Also surface legacy previous_investigations when similar context is empty.
    if not lines:
        investigation_context = context_pack.get("investigation_context") or {}
        for item in investigation_context.get("previous_investigations") or []:
            if not isinstance(item, dict):
                continue
            lines.append(
                "Historical incident "
                f"{item.get('investigation_id') or item.get('ticket_key')}: "
                f"{item.get('match_reason') or 'similar investigation'}"
            )

    deduped: list[str] = []
    for line in lines:
        text = str(line).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:limit]


def _multi_agent_prompt_block(context_pack: Mapping[str, Any]) -> dict[str, Any]:
    findings = context_pack.get("multi_agent_findings") or {}
    if not isinstance(findings, dict) or not findings:
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "timeline_findings",
        "deployment_findings",
        "infrastructure_findings",
        "incident_findings",
        "knowledge_findings",
        "rca_findings",
    ):
        value = findings.get(key)
        if isinstance(value, dict) and value.get("summary"):
            compact[key] = {
                "summary": value.get("summary"),
                "key_observations": list(value.get("key_observations") or [])[:3],
                "confidence": value.get("confidence"),
            }
    if findings.get("final_summary"):
        compact["final_summary"] = findings.get("final_summary")
    return compact


def _ticket_context_block(context_pack: Mapping[str, Any]) -> dict[str, Any]:
    jira = context_pack.get("jira_ticket_context") or {}
    if not isinstance(jira, dict) or not any(jira.get(key) for key in ("summary", "issue_key")):
        return {}
    return {
        "issue_key": jira.get("issue_key"),
        "summary": jira.get("summary"),
        "description": jira.get("description"),
        "priority": jira.get("priority"),
        "status": jira.get("status"),
        "labels": list(jira.get("labels") or [])[:8],
    }


def _signal_lines_from_primary(primary_full: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(primary_full, Mapping):
        return []
    lines: list[str] = []
    for entry in primary_full.get("signal_summary") or []:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or "").strip()
        score = entry.get("score")
        if not name:
            continue
        if score is None:
            lines.append(name)
        else:
            lines.append(f"{name}={score}")
    assessment = primary_full.get("confidence_assessment") or {}
    if isinstance(assessment, Mapping):
        for factor in assessment.get("supporting_factors") or []:
            text = str(factor).strip()
            if text and text not in lines:
                lines.append(text)
    return lines[:8]


def _deployment_commit_block(primary_full: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(primary_full, Mapping):
        return {}
    cde = primary_full.get("commit_deployment_evidence") or {}
    if not isinstance(cde, Mapping):
        return {}
    out = {k: v for k, v in cde.items() if v not in (None, "", False, [], {})}
    return out


def _graph_context_lines(context_pack: Mapping[str, Any], *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    inv = context_pack.get("investigation_context") or {}
    if not isinstance(inv, dict):
        return lines
    for key, label in (
        ("related_deployments", "deployment"),
        ("related_alerts", "alert"),
        ("related_incidents", "incident"),
        ("recent_commits", "commit"),
        ("runbooks", "runbook"),
        ("previous_investigations", "prior investigation"),
    ):
        for item in inv.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name")
                or item.get("id")
                or item.get("sha")
                or item.get("title")
                or item.get("investigation_id")
                or item.get("ticket_key")
                or ""
            )
            detail = item.get("summary") or item.get("match_reason") or item.get("status") or ""
            text = f"{label}: {name}"
            if detail:
                text = f"{text} — {detail}"
            text = str(text).strip()
            if text and text not in lines:
                lines.append(text)
            if len(lines) >= limit:
                return lines
    return lines


def _missing_evidence_lines(
    *,
    ticket_context: Mapping[str, Any],
    stack_lines: list[str],
    log_lines: list[str],
    deploy_block: Mapping[str, Any],
    historical_incidents: list[str],
    graph_lines: list[str],
) -> list[str]:
    missing: list[str] = []
    if not ticket_context or not (ticket_context.get("issue_key") or ticket_context.get("summary")):
        missing.append(
            "No usable JIRA ticket summary is present; base the incident context primarily on "
            "uploaded log and stack-trace evidence."
        )
    if not stack_lines:
        missing.append("No stack-trace evidence bullets were supplied.")
    if not log_lines:
        missing.append("No explicit log-evidence bullets were supplied.")
    if not deploy_block:
        missing.append("No deployment or commit linkage was supplied for the selected candidate.")
    if not historical_incidents:
        missing.append("No historical incident matches were supplied.")
    if not graph_lines:
        missing.append("No additional graph relationship context was supplied.")
    return missing


def _format_labeled_user_prompt(sections: Mapping[str, Any]) -> str:
    """Render labeled sections for the LLM user message (still followed by JSON output contract)."""
    lines: list[str] = [
        "Explain the deterministic RCA result using ONLY the sections below.",
        "Return JSON with keys: explanation_summary, evidence_highlights, "
        "confidence_alignment_note, optional_patch_direction, limitations.",
        "explanation_summary must be 180-300 words across 2-4 paragraphs of plain text.",
        "",
    ]
    for title, value in sections.items():
        lines.append(f"## {title}")
        if value is None or value == "" or value == [] or value == {}:
            lines.append("(none provided)")
        elif isinstance(value, list):
            for item in value:
                lines.append(f"- {item}")
        elif isinstance(value, Mapping):
            lines.append(json.dumps(value, ensure_ascii=True, indent=2))
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines).strip()


def build_minimal_deterministic_prompt(
    context_pack: Mapping[str, Any],
    summarized_evidence: list[Mapping[str, Any]] | list[str],
) -> dict[str, str]:
    """
    Ollama/local-LLM prompt: structured labeled sections from deterministic context only.

    Included: anomaly_id, primary file path, primary confidence, evidence highlight strings,
    ticket/log/stack/deployment/graph context, and missing-evidence notes.
    """
    ranked = _extract_ranked_candidates(context_pack, max_candidates=3)
    primary = ranked[0] if ranked else {}
    primary_path = str(primary.get("path") or "")
    primary_confidence = float(primary.get("confidence") or 0.0)
    bullets = _evidence_bullet_strings(summarized_evidence)
    limitations_context = str(context_pack.get("limitations_context") or "").strip()
    jira_ticket_context = context_pack.get("jira_ticket_context") or {}
    ticket_context = _ticket_context_block(context_pack)
    historical_feedback = _historical_feedback_lines(context_pack)
    historical_incidents = _historical_incident_lines(context_pack)
    multi_agent_findings = _multi_agent_prompt_block(context_pack)

    primary_full = None
    raw_candidates = context_pack.get("candidates") or []
    if isinstance(raw_candidates, list) and raw_candidates and isinstance(raw_candidates[0], Mapping):
        primary_full = raw_candidates[0]

    stack_lines = _bullets_by_category(summarized_evidence, {"stack"})
    log_lines = _bullets_by_category(summarized_evidence, {"log", "keyword", "path", "error"})
    if not log_lines:
        # Fall back to non-stack/non-candidate evidence phrasing that often carries log facts.
        log_lines = _bullets_by_category(
            summarized_evidence,
            {"candidate", "commit", "deployment", "recurrence", "signal", "jira"},
        )
    supporting_signals = _signal_lines_from_primary(primary_full)
    if not supporting_signals:
        supporting_signals = bullets[:8]
    deploy_block = _deployment_commit_block(primary_full)
    graph_lines = _graph_context_lines(context_pack)
    missing = _missing_evidence_lines(
        ticket_context=ticket_context,
        stack_lines=stack_lines,
        log_lines=log_lines,
        deploy_block=deploy_block,
        historical_incidents=historical_incidents,
        graph_lines=graph_lines,
    )
    if limitations_context:
        missing.append(limitations_context)

    incident_context: dict[str, Any] = {
        "anomaly_id": context_pack.get("anomaly_id"),
        "Ticket Context": ticket_context or jira_ticket_context or {},
        "ticket_unavailable_guidance": (
            "If ticket data is missing or UNKNOWN, state that analysis is primarily based on "
            "uploaded log and stack-trace evidence; do not dwell on the missing ticket."
        ),
    }

    sections = {
        "INCIDENT CONTEXT": incident_context,
        "SELECTED RCA CANDIDATE": {
            "path": primary_path,
            "file_id": primary.get("file_id"),
            "rank": primary.get("rank", 1),
            "evidence_ref": primary.get("evidence_ref"),
        },
        "CONFIDENCE": {
            "deterministic_confidence": primary_confidence,
            "note": "Use this confidence exactly when mentioning a score; do not invent another.",
        },
        "SUPPORTING SIGNALS": supporting_signals,
        "STACK-TRACE EVIDENCE": stack_lines,
        "LOG EVIDENCE": log_lines,
        "DEPLOYMENT OR COMMIT CONTEXT": deploy_block,
        "GRAPH CONTEXT": {
            "relationships": graph_lines,
            "Historical Feedback": historical_feedback,
            "Historical Incidents": historical_incidents,
            "Multi-Agent Findings": multi_agent_findings,
            "Agent Findings": multi_agent_findings,
        },
        "MISSING EVIDENCE": missing,
        "EVIDENCE HIGHLIGHTS (copy for evidence_highlights)": bullets[:12],
        "OUTPUT CONTRACT": {
            "json_only": True,
            "required_keys": [
                "explanation_summary",
                "evidence_highlights",
                "confidence_alignment_note",
                "optional_patch_direction",
                "limitations",
            ],
            "must_not_invent_entities": True,
            "must_not_rerank": True,
            "patch_direction_advisory_only": True,
            "explanation_summary_words": "180-300",
            "explanation_summary_paragraphs": "2-4",
        },
    }

    # Preserve machine-readable keys expected by existing tests / consumers.
    compact_json = {
        "deterministic_context": {
            "anomaly_id": context_pack.get("anomaly_id"),
            "primary_candidate_file_path": primary_path,
            "primary_confidence": primary_confidence,
            "evidence_highlights": bullets[:12],
            "limitations_context": limitations_context,
            "jira_ticket_context": jira_ticket_context,
            "Ticket Context": ticket_context,
            "Historical Feedback": historical_feedback,
            "Historical Incidents": historical_incidents,
            "Multi-Agent Findings": multi_agent_findings,
            "Agent Findings": multi_agent_findings,
        },
        "labeled_sections": list(sections.keys()),
    }

    user_prompt = (
        _format_labeled_user_prompt(sections)
        + "\n\n## MACHINE-READABLE DETERMINISTIC CONTEXT\n"
        + json.dumps(compact_json, ensure_ascii=True, separators=(",", ":"))
    )
    return {
        "system": MINIMAL_DETERMINISTIC_SYSTEM_PROMPT,
        "user": user_prompt,
    }
