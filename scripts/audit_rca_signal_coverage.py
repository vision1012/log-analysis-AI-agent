#!/usr/bin/env python3
"""
RCA signal coverage audit — read-only static analysis.

Verifies signal sources, weights, and usage across ranking, confidence, and reports.

Does not modify runtime behavior or business logic.

Usage::

    python scripts/audit_rca_signal_coverage.py
    python scripts/audit_rca_signal_coverage.py --output-dir artifacts/audit
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from rca_engine.ranking_model import DEFAULT_WEIGHTS, MCP_DEFAULT_WEIGHTS

UsageStatus = Literal["yes", "no", "partial"]

SIGNAL_IDS: tuple[str, ...] = (
    "stack_trace",
    "keyword",
    "ownership",
    "graph",
    "deployment",
    "alert",
    "historical_incident",
    "known_issue",
    "coverage",
)

SIGNAL_LABELS: dict[str, str] = {
    "stack_trace": "Stack Trace Signal",
    "keyword": "Keyword Signal",
    "ownership": "Ownership Signal",
    "graph": "Graph Signal",
    "deployment": "Deployment Signal",
    "alert": "Alert Signal",
    "historical_incident": "Historical Incident Signal",
    "known_issue": "Known Issue Signal",
    "coverage": "Coverage Signal",
}


@dataclass
class SignalAuditResult:
    signal_id: str
    label: str
    signal_source: str
    signal_weight: str
    used_in_ranking: UsageStatus
    used_in_confidence: UsageStatus
    used_in_report: UsageStatus
    implementation_keys: list[str] = None  # type: ignore[assignment]
    notes: str = ""

    def __post_init__(self) -> None:
        if self.implementation_keys is None:
            self.implementation_keys = []


@dataclass
class RCAAuditReport:
    generated_at: str
    repo_root: str
    signals: list[SignalAuditResult] = None  # type: ignore[assignment]
    summary: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.signals is None:
            self.signals = []
        if self.summary is None:
            self.summary = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "summary": self.summary,
            "signals": [asdict(signal) for signal in self.signals],
        }


def _read_text(relative_path: str) -> str:
    path = _REPO / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _files_exist(relative_paths: list[str]) -> list[str]:
    return [rel for rel in relative_paths if (_REPO / rel).is_file()]


def _has_any(files: list[str], patterns: list[str]) -> bool:
    for rel in files:
        text = _read_text(rel)
        if not text:
            continue
        if any(pattern in text for pattern in patterns):
            return True
    return False


def _weight_summary(keys: list[str], *, mcp: bool = False, include_graph: bool = False) -> str:
    parts: list[str] = []
    total = 0.0
    if include_graph or not mcp:
        for key in keys:
            if key in DEFAULT_WEIGHTS:
                parts.append(f"{key}={DEFAULT_WEIGHTS[key]:.2f}")
                total += DEFAULT_WEIGHTS[key]
    if mcp or include_graph:
        for key in keys:
            if key in MCP_DEFAULT_WEIGHTS:
                parts.append(f"{key}={MCP_DEFAULT_WEIGHTS[key]:.2f}")
                total += MCP_DEFAULT_WEIGHTS[key]
    if not parts:
        return "n/a (not in ranking weights)"
    return f"{', '.join(parts)} (nominal sum={total:.2f})"


def _classify_usage(
    *,
    ranking_patterns: list[str],
    confidence_patterns: list[str],
    report_patterns: list[str],
    ranking_files: list[str] | None = None,
    confidence_files: list[str] | None = None,
    report_files: list[str] | None = None,
) -> tuple[UsageStatus, UsageStatus, UsageStatus]:
    ranking_files = ranking_files or ["rca_engine/ranking_model.py", "rca_engine/signal_computation.py"]
    confidence_files = confidence_files or ["rca_engine/confidence_engine.py"]
    report_files = report_files or [
        "reporting/report_builder.py",
        "reporting/report_models.py",
        "reporting/markdown_exporter.py",
        "agents/rca_agent.py",
    ]

    ranking = "yes" if _has_any(_files_exist(ranking_files), ranking_patterns) else "no"
    confidence = "yes" if _has_any(_files_exist(confidence_files), confidence_patterns) else "no"

    report_hits = 0
    for rel in _files_exist(report_files):
        text = _read_text(rel)
        if any(pattern in text for pattern in report_patterns):
            report_hits += 1

    if report_hits >= 2 or (
        report_hits == 1 and any(p in ("evidence_coverage", "EvidenceCoverageSection") for p in report_patterns)
    ):
        report: UsageStatus = "yes"
    elif report_hits == 1:
        report = "partial"
    else:
        report = "no"

    return ranking, confidence, report


SIGNAL_RULES: dict[str, dict[str, Any]] = {
    "stack_trace": {
        "keys": ["top_frame_presence", "frame_depth_penalty", "trace_completeness"],
        "source": "Neo4j stack frames (`HAS_FRAME`, `frame_order`) via `signal_computation.py`",
        "ranking_patterns": ["top_frame_presence", "frame_depth_penalty", "trace_completeness"],
        "confidence_patterns": ["top_frame_presence", "trace_completeness", "weak_trace", "top stack frame"],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "stack"],
        "notes": "Primary deterministic stack-trace attribution signals.",
    },
    "keyword": {
        "keys": ["keyword_alignment"],
        "source": "Log text keyword extraction (`compute_log_keyword_signal`) integrated in `compute_signals`",
        "ranking_patterns": ["keyword_alignment"],
        "confidence_patterns": ["keyword_alignment", "Strong keyword alignment", "No keyword alignment"],
        "report_patterns": ["keyword_evidence", "KeywordEvidenceSection", "Keyword Evidence", "matched_keywords"],
        "ranking_files": ["rca_engine/ranking_model.py", "rca_engine/signal_computation.py"],
        "confidence_files": ["rca_engine/confidence_engine.py"],
        "report_files": ["reporting/report_builder.py", "reporting/report_models.py", "reporting/markdown_exporter.py"],
        "notes": "First-class RCA signal with default weight 0.08 (normalized in effective_weights).",
    },
    "ownership": {
        "keys": [],
        "source": "Not implemented",
        "ranking_patterns": ["ownership"],
        "confidence_patterns": ["ownership"],
        "report_patterns": ["ownership"],
        "notes": "No ownership/code-owner signal exists in the RCA engine.",
    },
    "graph": {
        "keys": [
            "last_touch_recency",
            "historical_recurrence",
            "resolution_quality",
            "file_touch_sparsity",
            "spike_correlation_strength",
        ],
        "source": "Neo4j graph metadata (commits, recurrence, resolution, touch sparsity)",
        "ranking_patterns": [
            "last_touch_recency",
            "historical_recurrence",
            "resolution_quality",
            "file_touch_sparsity",
            "spike_correlation_strength",
        ],
        "confidence_patterns": [
            "graph_strength",
            "strong_graph_evidence",
            "moderate_graph_evidence",
            "resolution_quality",
            "last_touch_recency",
        ],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "graph evidence"],
        "notes": "Composite graph evidence beyond stack trace and deployment proximity.",
    },
    "deployment": {
        "keys": ["deploy_proximity", "deploy_recency_rank", "deployment_proximity_mcp"],
        "source": "Neo4j deployments + MCP investigation graph deployment events",
        "mcp": True,
        "ranking_patterns": ["deploy_proximity", "deploy_recency_rank", "deployment_proximity_mcp"],
        "confidence_patterns": [
            "deployment_proximity_mcp",
            "deploy_proximity",
            "deploy_recency_rank",
            "Deployment occurred within",
        ],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "Deployment"],
        "notes": "Graph deploy proximity plus MCP time-bucket bonus points.",
    },
    "alert": {
        "keys": ["alert_correlation"],
        "source": "MCP/Datadog alert events from investigation graph context",
        "mcp": True,
        "ranking_patterns": ["alert_correlation"],
        "confidence_patterns": ["alert_correlation", "Critical alert", "Warning alert"],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "alert"],
        "notes": "Severity-weighted alert correlation with optional repeat bonus.",
    },
    "historical_incident": {
        "keys": ["historical_recurrence", "historical_investigation"],
        "source": "Neo4j prior RCA attributions + similar investigation retrieval",
        "mcp": True,
        "ranking_patterns": ["historical_recurrence", "historical_investigation"],
        "confidence_patterns": [
            "historical_recurrence",
            "historical_investigation",
            "Repeated historical incidents",
            "Prior investigations attributed",
        ],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "historical"],
        "notes": "Includes graph recurrence and MCP similar-investigation boost.",
    },
    "known_issue": {
        "keys": ["known_issue_match"],
        "source": "Confluence/Neo4j known issues matched to candidate path or service",
        "mcp": True,
        "ranking_patterns": ["known_issue_match"],
        "confidence_patterns": ["known_issue_match", "known issue"],
        "report_patterns": ["confidence_reasoning", "supporting_factors", "known issue"],
        "notes": "Documented known-issue alignment adds MCP ranking bonus points.",
    },
    "coverage": {
        "keys": [],
        "source": "MCP `evidence_coverage` metadata merged in confidence engine",
        "ranking_patterns": ["coverage_score", "evidence_coverage"],
        "confidence_patterns": ["coverage_score", "coverage_level", "_coverage_metadata", "evidence_coverage"],
        "report_patterns": ["evidence_coverage", "EvidenceCoverageSection", "confidence_limitations"],
        "ranking_files": ["rca_engine/confidence_engine.py", "mcp/evidence_coverage.py"],
        "notes": "Coverage metadata and limitations only; does not change deterministic ranking scores.",
    },
}


def _audit_signal(signal_id: str) -> SignalAuditResult:
    rules = SIGNAL_RULES[signal_id]
    keys: list[str] = list(rules.get("keys") or [])
    mcp = bool(rules.get("mcp"))

    if signal_id == "ownership":
        return SignalAuditResult(
            signal_id=signal_id,
            label=SIGNAL_LABELS[signal_id],
            signal_source=rules["source"],
            signal_weight="n/a",
            used_in_ranking="no",
            used_in_confidence="no",
            used_in_report="no",
            implementation_keys=[],
            notes=rules["notes"],
        )

    if signal_id == "coverage":
        ranking, confidence, report = _classify_usage(
            ranking_patterns=rules["ranking_patterns"],
            confidence_patterns=rules["confidence_patterns"],
            report_patterns=rules["report_patterns"],
            ranking_files=rules.get("ranking_files"),
        )
        ranking = "no"  # by design: coverage does not affect rank_candidates
        return SignalAuditResult(
            signal_id=signal_id,
            label=SIGNAL_LABELS[signal_id],
            signal_source=rules["source"],
            signal_weight="metadata only (no ranking weight)",
            used_in_ranking=ranking,
            used_in_confidence="yes" if confidence == "yes" else "partial",
            used_in_report=report,
            implementation_keys=["evidence_coverage", "coverage_score", "coverage_level"],
            notes=rules["notes"],
        )

    ranking, confidence, report = _classify_usage(
        ranking_patterns=rules["ranking_patterns"],
        confidence_patterns=rules["confidence_patterns"],
        report_patterns=rules["report_patterns"],
        ranking_files=rules.get("ranking_files"),
        confidence_files=rules.get("confidence_files"),
        report_files=rules.get("report_files"),
    )

    weight = _weight_summary(keys, mcp=mcp, include_graph=mcp)
    if signal_id in {"stack_trace", "graph"}:
        weight = _weight_summary(keys, mcp=False)

    # Reports surface signals indirectly via confidence_reasoning, not per-signal tables.
    if report == "yes" and signal_id not in {"coverage", "keyword"}:
        report = "partial"

    return SignalAuditResult(
        signal_id=signal_id,
        label=SIGNAL_LABELS[signal_id],
        signal_source=rules["source"],
        signal_weight=weight,
        used_in_ranking=ranking,
        used_in_confidence=confidence,
        used_in_report=report,
        implementation_keys=keys,
        notes=rules.get("notes", ""),
    )


def run_audit() -> RCAAuditReport:
    signals = [_audit_signal(signal_id) for signal_id in SIGNAL_IDS]
    summary = {
        "total": len(signals),
        "ranking_yes": sum(1 for s in signals if s.used_in_ranking == "yes"),
        "ranking_partial": sum(1 for s in signals if s.used_in_ranking == "partial"),
        "confidence_yes": sum(1 for s in signals if s.used_in_confidence == "yes"),
        "report_yes": sum(1 for s in signals if s.used_in_report == "yes"),
        "report_partial": sum(1 for s in signals if s.used_in_report == "partial"),
        "missing": sum(1 for s in signals if s.signal_id == "ownership"),
    }
    return RCAAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(_REPO),
        signals=signals,
        summary=summary,
    )


def _status_cell(status: UsageStatus) -> str:
    return status.upper()


def render_markdown(report: RCAAuditReport) -> str:
    lines = [
        "# RCA Signal Coverage Audit",
        "",
        f"**Generated:** {report.generated_at}",
        f"**Repository:** `{report.repo_root}`",
        "",
        "## Summary",
        "",
        f"- Signals audited: {report.summary.get('total', 0)}",
        f"- Used in ranking: {report.summary.get('ranking_yes', 0)} yes, "
        f"{report.summary.get('ranking_partial', 0)} partial",
        f"- Used in confidence: {report.summary.get('confidence_yes', 0)} yes",
        f"- Used in report: {report.summary.get('report_yes', 0)} yes, "
        f"{report.summary.get('report_partial', 0)} partial",
        f"- Missing implementations: {report.summary.get('missing', 0)}",
        "",
        "Ranking weights loaded from `rca_engine.ranking_model.DEFAULT_WEIGHTS` and "
        "`MCP_DEFAULT_WEIGHTS`. MCP point bonuses are additive via `score_breakdown`.",
        "",
        "## Signal Coverage Matrix",
        "",
        "| Signal | Signal Source | Signal Weight | Used In Ranking | Used In Confidence | Used In Report |",
        "|--------|---------------|---------------|-----------------|--------------------|----------------|",
    ]

    for signal in report.signals:
        lines.append(
            f"| {signal.label} | {signal.signal_source} | {signal.signal_weight} | "
            f"{_status_cell(signal.used_in_ranking)} | {_status_cell(signal.used_in_confidence)} | "
            f"{_status_cell(signal.used_in_report)} |"
        )

    lines.extend(["", "## Per-Signal Detail", ""])
    for signal in report.signals:
        lines.append(f"### {signal.label}")
        lines.append("")
        if signal.implementation_keys:
            lines.append(f"- **Implementation keys:** `{', '.join(signal.implementation_keys)}`")
        lines.append(f"- **Signal source:** {signal.signal_source}")
        lines.append(f"- **Signal weight:** {signal.signal_weight}")
        lines.append(f"- **Used in ranking:** {_status_cell(signal.used_in_ranking)}")
        lines.append(f"- **Used in confidence:** {_status_cell(signal.used_in_confidence)}")
        lines.append(f"- **Used in report:** {_status_cell(signal.used_in_report)}")
        if signal.notes:
            lines.append(f"- **Note:** {signal.notes}")
        lines.append("")

    lines.extend(
        [
            "## Gaps and Observations",
            "",
            "- **Ownership Signal** is not implemented anywhere in the RCA engine.",
            "- **Keyword Signal** is limited to the Jira log-only fallback path; it is outside core "
            "`run_rca` weighted ranking.",
            "- **Coverage Signal** affects confidence limitations and report sections but intentionally "
            "does not change deterministic candidate ranking.",
            "- Most signals appear in reports only indirectly through `confidence_reasoning` text "
            "(supporting/contradicting factors), not as a dedicated per-signal section.",
            "- **incident_severity** (PagerDuty urgency MCP bonus) exists in `signal_computation.py` but "
            "is not listed as a separate audited signal category.",
            "",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def write_reports(report: RCAAuditReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rca_audit_report.json"
    md_path = output_dir / "rca_audit_report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def print_console_summary(report: RCAAuditReport) -> None:
    print("=== RCA Signal Coverage Audit ===")
    print(f"generated_at={report.generated_at}")
    print()
    for signal in report.signals:
        print(
            f"{signal.label}: ranking={signal.used_in_ranking} "
            f"confidence={signal.used_in_confidence} report={signal.used_in_report}"
        )
    print()
    print(f"Summary: {report.summary}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit RCA signal coverage.")
    parser.add_argument(
        "--output-dir",
        default=str(_REPO / "artifacts" / "audit"),
        help="Directory for rca_audit_report.md and rca_audit_report.json",
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
