#!/usr/bin/env python3
"""
GraphRAG context completeness audit — read-only static analysis.

Verifies which MCP provider data and investigation context types reach the GraphRAG
pipeline (pack, LLM prompt, narrative, output) and classifies each as USED,
AVAILABLE BUT UNUSED, or MISSING.

Does not modify runtime behavior or business logic.

Usage::

    python scripts/audit_graphrag_context.py
    python scripts/audit_graphrag_context.py --output-dir artifacts/audit
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

ContextStatus = Literal["used", "available_but_unused", "missing"]

DISPLAY_STATUS: dict[ContextStatus, str] = {
    "used": "USED",
    "available_but_unused": "AVAILABLE BUT UNUSED",
    "missing": "MISSING",
}

GRAPHRAG_FILES = [
    "graphrag/context_packer.py",
    "graphrag/explanation_generator.py",
    "graphrag/narrative_generator.py",
    "graphrag/prompt_builder.py",
    "graphrag/evidence_summarizer.py",
    "graphrag/output_validator.py",
]

PROVIDER_ITEMS: tuple[str, ...] = (
    "jira",
    "github",
    "gitlab",
    "jenkins",
    "datadog",
    "kubernetes",
    "pagerduty",
    "confluence",
)

CONTEXT_ITEMS: tuple[str, ...] = (
    "timeline",
    "graph_entities",
    "deployments",
    "alerts",
    "incidents",
    "runbooks",
    "known_issues",
    "feedback",
    "similar_incidents",
    "coverage_information",
    "confidence_information",
    "multi_agent_findings",
)

PROVIDER_LABELS: dict[str, str] = {
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "jenkins": "Jenkins",
    "datadog": "Datadog",
    "kubernetes": "Kubernetes",
    "pagerduty": "PagerDuty",
    "confluence": "Confluence",
}

CONTEXT_LABELS: dict[str, str] = {
    "timeline": "Timeline",
    "graph_entities": "Graph Entities",
    "deployments": "Deployments",
    "alerts": "Alerts",
    "incidents": "Incidents",
    "runbooks": "Runbooks",
    "known_issues": "Known Issues",
    "feedback": "Feedback",
    "similar_incidents": "Similar Incidents",
    "coverage_information": "Coverage Information",
    "confidence_information": "Confidence Information",
    "multi_agent_findings": "Multi-Agent Findings",
}


@dataclass
class ContextPath:
    stage: str
    detail: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class ContextAuditResult:
    item_id: str
    label: str
    category: str
    status: ContextStatus
    display_status: str
    receive_paths: list[ContextPath] = field(default_factory=list)
    use_paths: list[ContextPath] = field(default_factory=list)
    notes: str = ""


@dataclass
class GraphRAGAuditReport:
    generated_at: str
    repo_root: str
    providers: list[ContextAuditResult] = field(default_factory=list)
    contexts: list[ContextAuditResult] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    available_but_unused: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "summary": self.summary,
            "used": self.used,
            "available_but_unused": self.available_but_unused,
            "missing": self.missing,
            "providers": [_item_dict(item) for item in self.providers],
            "contexts": [_item_dict(item) for item in self.contexts],
            "unused_packed_fields": _collect_unused_packed_fields(),
        }


def _item_dict(item: ContextAuditResult) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "label": item.label,
        "category": item.category,
        "status": item.display_status,
        "status_key": item.status,
        "receive_paths": [asdict(path) for path in item.receive_paths],
        "use_paths": [asdict(path) for path in item.use_paths],
        "notes": item.notes,
    }


def _read_text(relative_path: str) -> str:
    path = _REPO / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _files_exist(relative_paths: list[str]) -> list[str]:
    return [rel for rel in relative_paths if (_REPO / rel).is_file()]


def _match_patterns(files: list[str], patterns: list[str]) -> list[str]:
    evidence: list[str] = []
    for rel in files:
        text = _read_text(rel)
        if not text:
            continue
        for pattern in patterns:
            if pattern in text:
                evidence.append(f"{rel}: {pattern}")
    return evidence


def _classify_status(*, has_receive: bool, has_use: bool, special: ContextStatus | None = None) -> ContextStatus:
    if special is not None:
        return special
    if has_use:
        return "used"
    if has_receive:
        return "available_but_unused"
    return "missing"


def _make_result(
    item_id: str,
    label: str,
    category: str,
    *,
    receive_rule: dict[str, Any],
    use_rule: dict[str, Any],
    notes: str = "",
    special: ContextStatus | None = None,
) -> ContextAuditResult:
    receive_files = _files_exist(receive_rule["files"])
    use_files = _files_exist(use_rule["files"])
    receive_evidence = _match_patterns(receive_files, receive_rule["patterns"])
    use_evidence = _match_patterns(use_files, use_rule["patterns"])
    has_receive = bool(receive_evidence)
    has_use = bool(use_evidence)
    status = _classify_status(has_receive=has_receive, has_use=has_use, special=special)

    return ContextAuditResult(
        item_id=item_id,
        label=label,
        category=category,
        status=status,
        display_status=DISPLAY_STATUS[status],
        receive_paths=[
            ContextPath(
                stage=receive_rule["stage"],
                detail=receive_rule["detail"],
                evidence=receive_evidence,
            )
        ]
        if has_receive
        else [],
        use_paths=[
            ContextPath(
                stage=use_rule["stage"],
                detail=use_rule["detail"],
                evidence=use_evidence,
            )
        ]
        if has_use
        else [],
        notes=notes,
    )


# MCP provider rules: receive = reaches GraphRAG; use = consumed in narrative/LLM/output.
PROVIDER_RULES: dict[str, dict[str, Any]] = {
    "jira": {
        "receive": {
            "stage": "pack_or_input",
            "files": GRAPHRAG_FILES + ["api/services/rca_service.py"],
            "patterns": ["ticket_key", "get_previous_similar_investigations"],
            "detail": "ticket_key parameter and similar-investigation retrieval (Jira-linked)",
        },
        "use": {
            "stage": "narrative_or_llm",
            "files": GRAPHRAG_FILES,
            "patterns": ["ticket_context", "JiraTicket", "issue_key"],
            "detail": "explicit Jira ticket fields in narrative, summarizer, or LLM prompt",
        },
        "notes": "Jira ticket_key is received for Neo4j retrieval; ticket_context is not consumed downstream.",
    },
    "github": {
        "receive": {
            "stage": "unified_context_or_pack",
            "files": GRAPHRAG_FILES,
            "patterns": ["pull_requests", "related_commits", "commits"],
            "detail": "GitHub PRs/commits via unified context or Neo4j pack",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py", "graphrag/evidence_summarizer.py"],
            "patterns": ["pull_requests", "related_commits", "pr_merged", "category=\"commit\""],
            "detail": "timeline, causal chain, and commit evidence bullets",
        },
    },
    "gitlab": {
        "receive": {
            "stage": "unified_context",
            "files": GRAPHRAG_FILES,
            "patterns": ["merge_requests", "deployment_events"],
            "detail": "GitLab merge requests and deployments in unified context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["merge_requests", "deployment_events", "merge_request_merged"],
            "detail": "timeline and causal chain GitLab deployment/MR steps",
        },
    },
    "jenkins": {
        "receive": {
            "stage": "unified_context",
            "files": GRAPHRAG_FILES,
            "patterns": ["build_events"],
            "detail": "Jenkins build events in unified investigation context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["build_events", "build_completed"],
            "detail": "timeline and causal chain build steps",
        },
    },
    "datadog": {
        "receive": {
            "stage": "unified_context_or_pack",
            "files": GRAPHRAG_FILES,
            "patterns": ["alert_events", "metric_events", "trace_events", "related_alerts", "get_related_alerts"],
            "detail": "Datadog alerts/metrics/traces via unified context or Neo4j pack",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["alert_events", "metric_events", "related_alerts", "alert_fired", "metric_spike"],
            "detail": "timeline and causal chain alert/metric steps (trace_events not consumed)",
        },
        "notes": "trace_events are received via unified context but not referenced in narrative_generator.",
    },
    "kubernetes": {
        "receive": {
            "stage": "unified_context",
            "files": GRAPHRAG_FILES,
            "patterns": ["pod_events", "container_events", "node_events"],
            "detail": "Kubernetes pod/container/node events in unified context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["pod_events", "pod_restarted", "pod_failure"],
            "detail": "timeline and causal chain pod failure/restart steps",
        },
    },
    "pagerduty": {
        "receive": {
            "stage": "unified_context_or_pack",
            "files": GRAPHRAG_FILES,
            "patterns": ["pagerduty_incidents", "related_incidents", "get_related_incidents"],
            "detail": "PagerDuty incidents via unified context or Neo4j pack",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["pagerduty_incidents", "related_incidents", "pagerduty_incident_created"],
            "detail": "timeline, causal chain, and supporting evidence",
        },
    },
    "confluence": {
        "receive": {
            "stage": "unified_context_or_pack",
            "files": GRAPHRAG_FILES,
            "patterns": [
                "runbook_documents",
                "known_issue_documents",
                "architecture_documents",
                '"runbooks"',
                "get_runbooks_for_service",
            ],
            "detail": "Confluence runbooks/known issues/architecture via unified context or Neo4j",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": [
                "runbook_documents",
                "known_issue_documents",
                'graph_context.get("runbooks")',
                'graph_context.get("known_issues")',
            ],
            "detail": "supporting evidence and remediation from runbooks/known issues",
        },
        "notes": "architecture_documents are received but not consumed in narrative_generator.",
    },
}

# Investigation context rules.
CONTEXT_RULES: dict[str, dict[str, Any]] = {
    "timeline": {
        "receive": {
            "stage": "narrative_generation",
            "files": GRAPHRAG_FILES,
            "patterns": ["timeline_events", "_timeline_from_unified", "_timeline_from_graph"],
            "detail": "timeline assembled from unified and graph context",
        },
        "use": {
            "stage": "output",
            "files": ["graphrag/narrative_generator.py", "graphrag/explanation_generator.py"],
            "patterns": ['merged["timeline"]', "timeline_events", "attach_narrative_to_output"],
            "detail": "timeline events attached to explanation output",
        },
    },
    "graph_entities": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py", "graphrag/explanation_generator.py"],
            "patterns": ["investigation_context", "unified_investigation_context"],
            "detail": "Neo4j investigation_context block and optional unified MCP context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["graph_context.get(", "unified_context", "graph_ctx"],
            "detail": "graph entity fields drive timeline, causal chain, and evidence",
        },
    },
    "deployments": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ["related_deployments", "deployment_id", "deployment_timing_valid"],
            "detail": "Neo4j deployments plus RCA deployment linkage",
        },
        "use": {
            "stage": "narrative_summarizer",
            "files": ["graphrag/narrative_generator.py", "graphrag/evidence_summarizer.py"],
            "patterns": ["related_deployments", 'category="deployment"', "deployment_events"],
            "detail": "timeline, causal chain, and deployment evidence bullets",
        },
    },
    "alerts": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ["related_alerts", "get_related_alerts"],
            "detail": "Neo4j alert events in investigation_context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["related_alerts", "alert_events", "alert_fired"],
            "detail": "timeline and causal chain alert steps",
        },
    },
    "incidents": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ["related_incidents", "get_related_incidents"],
            "detail": "PagerDuty incidents in investigation_context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ["related_incidents", "pagerduty_incidents", "pagerduty_incident_created"],
            "detail": "timeline, causal chain, and supporting evidence",
        },
    },
    "runbooks": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ['"runbooks"', "get_runbooks_for_service"],
            "detail": "Neo4j runbooks in investigation_context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ['graph_context.get("runbooks")', "runbook_documents", "_build_remediation_candidates"],
            "detail": "supporting evidence and remediation candidates",
        },
    },
    "known_issues": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ['"known_issues"', "get_known_issues_for_alert"],
            "detail": "Neo4j known issues in investigation_context",
        },
        "use": {
            "stage": "narrative",
            "files": ["graphrag/narrative_generator.py"],
            "patterns": ['graph_context.get("known_issues")', "known_issue_documents"],
            "detail": "supporting evidence and remediation workarounds",
        },
    },
    "feedback": {
        "receive": {
            "stage": "context_pack",
            "files": GRAPHRAG_FILES,
            "patterns": ["feedback", "Feedback", "HAS_FEEDBACK", "feedback_history"],
            "detail": "operator feedback nodes or history",
        },
        "use": {
            "stage": "narrative_or_output",
            "files": GRAPHRAG_FILES,
            "patterns": ["feedback", "Feedback", "FEEDBACK", "feedback_history"],
            "detail": "feedback in narrative, output, or LLM prompt",
        },
        "notes": "No GraphRAG path retrieves or surfaces operator feedback.",
    },
    "similar_incidents": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ["previous_investigations", "get_previous_similar_investigations"],
            "detail": "prior similar investigations from Neo4j",
        },
        "use": {
            "stage": "narrative_or_llm",
            "files": [
                "graphrag/narrative_generator.py",
                "graphrag/prompt_builder.py",
                "graphrag/evidence_summarizer.py",
                "graphrag/explanation_generator.py",
            ],
            "patterns": ["previous_investigations", "similar_investigation", "similar incident"],
            "detail": "similar incidents in narrative, summarizer, or LLM prompt",
        },
        "notes": "Packed in investigation_context but not referenced downstream.",
    },
    "coverage_information": {
        "receive": {
            "stage": "context_pack_or_input",
            "files": [
                "graphrag/context_packer.py",
                "graphrag/explanation_generator.py",
                "rca_engine/confidence_engine.py",
            ],
            "patterns": ["evidence_coverage", "coverage_score", "coverage_level"],
            "detail": "MCP evidence coverage metadata",
        },
        "use": {
            "stage": "output",
            "files": [
                "graphrag/explanation_generator.py",
                "graphrag/narrative_generator.py",
                "rca_engine/confidence_engine.py",
            ],
            "patterns": ["coverage_score", "coverage_level", "confidence_limitations", "evidence_coverage"],
            "detail": "coverage fields in confidence reasoning, narrative, or explanation output",
        },
        "notes": "Coverage may arrive via candidate confidence_assessment (RCA upstream).",
    },
    "confidence_information": {
        "receive": {
            "stage": "context_pack",
            "files": ["graphrag/context_packer.py"],
            "patterns": ["confidence_assessment", "score_breakdown", '"confidence"'],
            "detail": "per-candidate confidence assessment and scores",
        },
        "use": {
            "stage": "output_and_narrative",
            "files": [
                "graphrag/explanation_generator.py",
                "graphrag/narrative_generator.py",
                "graphrag/prompt_builder.py",
            ],
            "patterns": [
                "confidence_assessment",
                "confidence_reasoning",
                "confidence_summary",
                "primary_confidence",
                "confidence_alignment_note",
            ],
            "detail": "confidence in output, narrative summary, and LLM scalar",
        },
    },
    "multi_agent_findings": {
        "receive": {
            "stage": "context_pack_or_input",
            "files": GRAPHRAG_FILES,
            "patterns": ["multi_agent", "MultiAgent", "agent_findings", "run_multi_agent_investigation"],
            "detail": "multi-agent investigation findings passed to GraphRAG",
        },
        "use": {
            "stage": "narrative_or_output",
            "files": GRAPHRAG_FILES,
            "patterns": ["multi_agent", "MultiAgent", "agent_findings", "agent_report"],
            "detail": "multi-agent findings in narrative, LLM prompt, or output",
        },
        "notes": "Multi-agent investigation is a separate API path; GraphRAG does not ingest agent reports.",
    },
}


def _audit_provider(provider_id: str) -> ContextAuditResult:
    rules = PROVIDER_RULES[provider_id]
    return _make_result(
        provider_id,
        PROVIDER_LABELS[provider_id],
        "provider",
        receive_rule=rules["receive"],
        use_rule=rules["use"],
        notes=str(rules.get("notes") or ""),
    )


def _audit_context_item(context_id: str) -> ContextAuditResult:
    rules = CONTEXT_RULES[context_id]
    special: ContextStatus | None = None

    if context_id == "coverage_information":
        receive_files = _files_exist(rules["receive"]["files"])
        use_files = _files_exist(rules["use"]["files"])
        receive_evidence = _match_patterns(receive_files, rules["receive"]["patterns"])
        use_evidence = _match_patterns(use_files, rules["use"]["patterns"])
        confidence_pack = _match_patterns(
            _files_exist(["graphrag/context_packer.py"]),
            ["confidence_assessment"],
        )
        confidence_use = _match_patterns(
            _files_exist(["graphrag/explanation_generator.py", "rca_engine/confidence_engine.py"]),
            ["coverage_score", "confidence_limitations", "build_confidence_reasoning"],
        )
        has_receive = bool(receive_evidence or confidence_pack)
        has_use = bool(use_evidence or confidence_use)
        return ContextAuditResult(
            item_id=context_id,
            label=CONTEXT_LABELS[context_id],
            category="context",
            status=_classify_status(has_receive=has_receive, has_use=has_use),
            display_status=DISPLAY_STATUS[_classify_status(has_receive=has_receive, has_use=has_use)],
            receive_paths=[
                ContextPath(
                    stage=rules["receive"]["stage"],
                    detail=rules["receive"]["detail"],
                    evidence=list(dict.fromkeys(receive_evidence + confidence_pack)),
                )
            ]
            if has_receive
            else [],
            use_paths=[
                ContextPath(
                    stage=rules["use"]["stage"],
                    detail=rules["use"]["detail"],
                    evidence=list(dict.fromkeys(use_evidence + confidence_use)),
                )
            ]
            if has_use
            else [],
            notes=str(rules.get("notes") or ""),
        )

    return _make_result(
        context_id,
        CONTEXT_LABELS[context_id],
        "context",
        receive_rule=rules["receive"],
        use_rule=rules["use"],
        notes=str(rules.get("notes") or ""),
        special=special,
    )


def _collect_unused_packed_fields() -> list[str]:
    """Additional packed fields with no downstream consumer in GraphRAG."""
    unused: list[str] = []

    narrative_text = _read_text("graphrag/narrative_generator.py")
    packer_text = _read_text("graphrag/context_packer.py")
    prompt_text = _read_text("graphrag/prompt_builder.py")

    if '"previous_investigations"' in packer_text and "previous_investigations" not in narrative_text:
        unused.append("investigation_context.previous_investigations")

    if "score_breakdown" in packer_text and "score_breakdown" not in narrative_text and "score_breakdown" not in prompt_text:
        unused.append("candidates[].score_breakdown")

    if "investigation_context" in packer_text and "investigation_context" not in prompt_text:
        unused.append("investigation_context (entire block excluded from minimal LLM prompt)")

    expl_text = _read_text("graphrag/explanation_generator.py")
    if "unified_investigation_context" in expl_text and "evidence_coverage" not in narrative_text:
        unused.append("unified_investigation_context.evidence_coverage (passed in, not read by narrative)")

    narrative = _read_text("graphrag/narrative_generator.py")
    if "trace_events" not in narrative and "trace_events" in _read_text("mcp/context/investigation_context.py"):
        unused.append("unified_context.trace_events (received upstream, not in narrative)")

    if "architecture_documents" not in narrative:
        unused.append("unified_context.architecture_documents (received upstream, not in narrative)")

    return unused


def _bucket_items(items: list[ContextAuditResult]) -> tuple[list[str], list[str], list[str]]:
    used = [item.label for item in items if item.status == "used"]
    available = [item.label for item in items if item.status == "available_but_unused"]
    missing = [item.label for item in items if item.status == "missing"]
    return used, available, missing


def run_audit() -> GraphRAGAuditReport:
    providers = [_audit_provider(provider_id) for provider_id in PROVIDER_ITEMS]
    contexts = [_audit_context_item(context_id) for context_id in CONTEXT_ITEMS]
    all_items = providers + contexts

    used, available, missing = _bucket_items(all_items)
    provider_used, provider_available, provider_missing = _bucket_items(providers)
    context_used, context_available, context_missing = _bucket_items(contexts)

    summary = {
        "used": len(used),
        "available_but_unused": len(available),
        "missing": len(missing),
        "total": len(all_items),
        "providers_used": len(provider_used),
        "providers_available_but_unused": len(provider_available),
        "providers_missing": len(provider_missing),
        "contexts_used": len(context_used),
        "contexts_available_but_unused": len(context_available),
        "contexts_missing": len(context_missing),
        "unused_packed_fields": len(_collect_unused_packed_fields()),
    }

    return GraphRAGAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO),
        providers=providers,
        contexts=contexts,
        used=used,
        available_but_unused=available,
        missing=missing,
        summary=summary,
    )


def _render_item_section(items: list[ContextAuditResult], title: str) -> list[str]:
    lines = [f"## {title}", ""]
    for item in items:
        lines.append(f"### {item.label}")
        lines.append("")
        lines.append(f"**Status:** {item.display_status}")
        if item.receive_paths:
            lines.append(f"- Receive: {item.receive_paths[0].detail}")
            for evidence in item.receive_paths[0].evidence[:3]:
                lines.append(f"  - `{evidence}`")
        else:
            lines.append("- Receive: not found")
        if item.use_paths:
            lines.append(f"- Use: {item.use_paths[0].detail}")
            for evidence in item.use_paths[0].evidence[:3]:
                lines.append(f"  - `{evidence}`")
        else:
            lines.append("- Use: not found")
        if item.notes:
            lines.append(f"- Note: {item.notes}")
        lines.append("")
    return lines


def render_markdown(report: GraphRAGAuditReport) -> str:
    unused_fields = _collect_unused_packed_fields()
    lines = [
        "# GraphRAG Context Completeness Audit",
        "",
        f"**Generated:** {report.generated_at}",
        f"**Repository:** `{report.repo_root}`",
        "",
        "## Summary",
        "",
        f"- USED: {report.summary.get('used', 0)}",
        f"- AVAILABLE BUT UNUSED: {report.summary.get('available_but_unused', 0)}",
        f"- MISSING: {report.summary.get('missing', 0)}",
        "",
        "GraphRAG pipeline stages audited: `pack_context` → `summarize_evidence` → "
        "`build_minimal_deterministic_prompt` (LLM) → `generate_investigation_narrative` → explanation output.",
        "",
        "## USED",
        "",
    ]

    if report.used:
        for label in report.used:
            lines.append(f"- **{label}**")
    else:
        lines.append("- _(none)_")

    lines.extend(["", "## AVAILABLE BUT UNUSED", ""])
    if report.available_but_unused:
        for label in report.available_but_unused:
            item = next(
                i for i in (*report.providers, *report.contexts) if i.label == label
            )
            lines.append(f"- **{label}**")
            if item.receive_paths:
                lines.append(f"  - Received: {item.receive_paths[0].detail}")
            if item.notes:
                lines.append(f"  - {item.notes}")
    else:
        lines.append("- _(none)_")

    lines.extend(["", "## MISSING", ""])
    if report.missing:
        for label in report.missing:
            item = next(
                i for i in (*report.providers, *report.contexts) if i.label == label
            )
            lines.append(f"- **{label}**")
            if item.notes:
                lines.append(f"  - {item.notes}")
    else:
        lines.append("- _(none)_")

    if unused_fields:
        lines.extend(["", "## Unused Packed Fields", ""])
        for field_name in unused_fields:
            lines.append(f"- `{field_name}`")

    lines.extend(_render_item_section(report.providers, "MCP Provider Detail"))
    lines.extend(_render_item_section(report.contexts, "Context Item Detail"))
    return "\n".join(lines).strip() + "\n"


def write_reports(report: GraphRAGAuditReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "graphrag_audit_report.json"
    md_path = output_dir / "graphrag_audit_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def print_console_summary(report: GraphRAGAuditReport) -> None:
    print("=== GraphRAG Context Completeness Audit ===")
    print(f"generated_at={report.generated_at}")
    print()
    print("--- MCP Providers ---")
    for item in report.providers:
        print(f"{item.display_status} {item.label}" + (f" — {item.notes}" if item.notes else ""))
    print()
    print("--- Context Items ---")
    for item in report.contexts:
        print(f"{item.display_status} {item.label}" + (f" — {item.notes}" if item.notes else ""))
    print()
    print(
        f"Summary: USED={report.summary.get('used', 0)} "
        f"AVAILABLE_BUT_UNUSED={report.summary.get('available_but_unused', 0)} "
        f"MISSING={report.summary.get('missing', 0)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit GraphRAG context completeness.")
    parser.add_argument(
        "--output-dir",
        default=str(_REPO / "artifacts" / "audit"),
        help="Directory for graphrag_audit_report.md and graphrag_audit_report.json",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress console summary")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_audit()
    json_path, md_path = write_reports(report, Path(args.output_dir))
    if not args.quiet:
        print_console_summary(report)
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
