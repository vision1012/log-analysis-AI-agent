"""
RCA runner: orchestrates pre_rca_gate, candidate generation, signal computation,
ranking, bundle-first evidence creation, and RCA_ATTRIBUTED edge writes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from artifacts.evidence_store import EvidenceStore
from gates.pre_rca_gate import GateResult, run_pre_rca_gate
from graph.neo4j_client import Neo4jClient
from graph.writer import GraphWriter

from rca_engine.candidate_generator import Candidate, generate_candidates
from rca_engine.confidence_engine import compute_confidence_for_ranked, build_confidence_graph_context
from rca_engine.ranking_model import RankedCandidate, rank_candidates
from rca_engine.signal_computation import (
    compute_signals,
    fetch_anomaly_context,
    fetch_file_metadata,
)


def _keyword_context_from_signals(signal_scores_by_file: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for raw in signal_scores_by_file.values():
        if isinstance(raw, dict) and raw.get("keyword_context_available"):
            return {"available": True}
    return {"available": False}


def run_deterministic_rca(
    anomaly_id: str,
    trigger_type: str,
    *,
    graph_client: Neo4jClient,
    graph_writer: GraphWriter,
    evidence_store: EvidenceStore,
    run_id: Optional[str] = None,
    override: bool = False,
    K_frames: int = 5,
    max_depth: int = 20,
    min_confidence: float = 0.25,
    mcp_graph_context: Optional[dict[str, Any]] = None,
    unified_investigation_context: Any = None,
    investigation_id: str = "",
    log_content: str = "",
) -> Optional["RCARunResult"]:
    """
    Execute deterministic RCA for one anomaly. Single transaction per anomaly.

    Flow:
    1. Run pre_rca_gate
    2. Generate candidates
    3. Compute signals
    4. Rank candidates
    5. Create evidence bundle (bundle-first)
    6. Write RCA_ATTRIBUTED edges to File (atomic)

    Edge properties: run_id, created_at, method='deterministic', confidence,
    status='candidate', evidence_ref.

    Returns RCARunResult or None if blocked/failed.
    """
    run_id = run_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    # 1. Pre-RCA gate
    gate_result = run_pre_rca_gate(
        graph_client,
        anomaly_id,
        run_id=run_id,
        trigger=trigger_type,
        override=override,
    )
    if gate_result.result == GateResult.BLOCK:
        return None

    # 2. Generate candidates
    candidates = generate_candidates(
        graph_client,
        anomaly_id,
        K_frames=K_frames,
        max_depth=max_depth,
        excluded_deployment_ids=gate_result.excluded_deployment_ids,
    )
    if not candidates:
        return None

    # 3. Compute signals
    signal_scores_by_file = compute_signals(
        graph_client,
        anomaly_id,
        candidates,
        max_depth=max_depth,
        excluded_deployment_ids=gate_result.excluded_deployment_ids,
        mcp_graph_context=mcp_graph_context,
        unified_investigation_context=unified_investigation_context,
        investigation_id=investigation_id,
        log_content=log_content,
    )
    if not signal_scores_by_file:
        return None

    keyword_context = _keyword_context_from_signals(signal_scores_by_file)

    # 4. Rank candidates
    ranked = rank_candidates(
        signal_scores_by_file,
        candidates=candidates,
        min_confidence=min_confidence,
    )
    if not ranked:
        return None

    confidence_assessments = [
        a.to_dict()
        for a in compute_confidence_for_ranked(
            ranked,
            graph_context=build_confidence_graph_context(
                mcp_graph_context,
                unified_investigation_context=unified_investigation_context,
                keyword_context=keyword_context,
            ),
        )
    ]

    cand_by_file = {c.file_id: c for c in candidates}
    ctx = fetch_anomaly_context(graph_client, anomaly_id, max_depth)
    file_metadata = fetch_file_metadata(
        graph_client,
        anomaly_id,
        [c.file_id for c in candidates],
        ctx,
        gate_result.excluded_deployment_ids,
    )

    # 5. Bundle-first: create and persist evidence bundles
    trace_ref = ctx.get("trace_ref") or ""
    bundle_ids: list[str] = []

    for i, r in enumerate(ranked):
        c = cand_by_file.get(r.file_id)
        meta = file_metadata.get(r.file_id, {})
        if not c:
            continue

        confidence_payload = confidence_assessments[i] if i < len(confidence_assessments) else {}
        raw_signals = signal_scores_by_file.get(r.file_id, {})
        keyword_signal = raw_signals.get("keyword_signal") if isinstance(raw_signals, dict) else None

        bundle_payload: dict[str, Any] = {
            "anomaly_id": anomaly_id,
            "trace_ref": trace_ref,
            "rca_run_id": run_id,
            "method": "deterministic",
            "attributed_file_id": r.file_id,
            "evidence_symbol": c.symbol_name or "",
            "last_touch_commit_sha": meta.get("last_commit_sha") or "",
            "signal_scores": r.signal_scores,
            "score_breakdown": r.score_breakdown,
            "weights_used": r.weights_used,
            "confidence_assessment": confidence_payload,
            "decision_timestamp": created_at,
            "schema_version": "1.0.0",
            "attributed_frame_id": r.frame_id,
            "frame_order": r.frame_order,
        }
        if isinstance(keyword_signal, dict):
            bundle_payload["keyword_signal"] = keyword_signal
        if meta.get("deployment_id"):
            bundle_payload["deployment_id"] = meta["deployment_id"]

        bundle_id = evidence_store.create_bundle(bundle_payload)
        bundle_ids.append(bundle_id)

    # 6. Write RCA_ATTRIBUTED to File (single transaction)
    batch: list[tuple[str, dict[str, Any]]] = []
    graph_writer.supersede_prior_attributions(anomaly_id, run_id, _batch=batch)

    for i, r in enumerate(ranked):
        if i < len(bundle_ids):
            graph_writer.write_rca_attributed_to_file(
                anomaly_id,
                r.file_id,
                run_id,
                "deterministic",
                r.capped_score if r.capped_score is not None else r.score,
                "candidate",
                bundle_ids[i],
                created_at,
                _batch=batch,
            )

    graph_writer.write_atomic(batch)

    return RCARunResult(
        run_id=run_id,
        anomaly_id=anomaly_id,
        attribution_count=len(ranked),
        bundle_ids=bundle_ids,
        confidence_assessments=confidence_assessments,
        ranked_candidates=[
            {
                "file_id": r.file_id,
                "path": r.path,
                "ranking_score": r.capped_score if r.capped_score is not None else r.score,
            }
            for r in ranked
        ],
    )


def run_rca(
    anomaly_id: str,
    *,
    graph_client: Neo4jClient,
    graph_writer: GraphWriter,
    evidence_store: EvidenceStore,
    run_id: Optional[str] = None,
    trigger: str = "auto",
    override: bool = False,
    K_frames: int = 5,
    max_depth: int = 20,
    top_n: int = 3,
    min_confidence: float = 0.25,
    mcp_graph_context: Optional[dict[str, Any]] = None,
    unified_investigation_context: Any = None,
    investigation_id: str = "",
    log_content: str = "",
) -> Optional["RCARunResult"]:
    """
    Execute full RCA pipeline for one anomaly.

    1. pre_rca_gate
    2. candidate generation
    3. signal computation
    4. ranking
    5. bundle-first evidence creation
    6. write RCA_ATTRIBUTED edges (atomic)

    Returns RCARunResult or None if blocked/failed.
    """
    run_id = run_id or str(uuid.uuid4())

    # 1. Pre-RCA gate
    gate_result = run_pre_rca_gate(
        graph_client,
        anomaly_id,
        run_id=run_id,
        trigger=trigger,
        override=override,
    )
    if gate_result.result == GateResult.BLOCK:
        return None

    # 2. Candidate generation
    candidates = generate_candidates(
        graph_client,
        anomaly_id,
        K_frames=K_frames,
        max_depth=max_depth,
        excluded_deployment_ids=gate_result.excluded_deployment_ids,
    )
    if not candidates:
        return None

    # 3. Signal computation
    signal_scores_by_file = compute_signals(
        graph_client,
        anomaly_id,
        candidates,
        max_depth=max_depth,
        excluded_deployment_ids=gate_result.excluded_deployment_ids,
        mcp_graph_context=mcp_graph_context,
        unified_investigation_context=unified_investigation_context,
        investigation_id=investigation_id,
        log_content=log_content,
    )
    if not signal_scores_by_file:
        return None

    keyword_context = _keyword_context_from_signals(signal_scores_by_file)

    # 4. Ranking
    ranked = rank_candidates(
        signal_scores_by_file,
        candidates=candidates,
        min_confidence=min_confidence,
    )
    if not ranked:
        return None

    confidence_assessments = [
        a.to_dict()
        for a in compute_confidence_for_ranked(
            ranked,
            graph_context=build_confidence_graph_context(
                mcp_graph_context,
                unified_investigation_context=unified_investigation_context,
                keyword_context=keyword_context,
            ),
        )
    ]

    cand_by_file = {c.file_id: c for c in candidates}
    ctx = fetch_anomaly_context(graph_client, anomaly_id, max_depth)
    file_metadata = fetch_file_metadata(
        graph_client,
        anomaly_id,
        [c.file_id for c in candidates],
        ctx,
        gate_result.excluded_deployment_ids,
    )

    # 5. Bundle-first: create and persist evidence bundles
    trace_ref = ctx.get("trace_ref") or ""
    decision_ts = datetime.now(timezone.utc).isoformat()
    bundle_ids: list[str] = []

    for i, r in enumerate(ranked):
        c = cand_by_file.get(r.file_id)
        meta = file_metadata.get(r.file_id, {})
        if not c:
            continue

        confidence_payload = confidence_assessments[i] if i < len(confidence_assessments) else {}
        raw_signals = signal_scores_by_file.get(r.file_id, {})
        keyword_signal = raw_signals.get("keyword_signal") if isinstance(raw_signals, dict) else None

        bundle_payload: dict[str, Any] = {
            "anomaly_id": anomaly_id,
            "trace_ref": trace_ref,
            "rca_run_id": run_id,
            "method": "deterministic",
            "attributed_file_id": r.file_id,
            "evidence_symbol": c.symbol_name or "",
            "last_touch_commit_sha": meta.get("last_commit_sha") or "",
            "signal_scores": r.signal_scores,
            "score_breakdown": r.score_breakdown,
            "weights_used": r.weights_used,
            "confidence_assessment": confidence_payload,
            "decision_timestamp": decision_ts,
            "schema_version": "1.0.0",
            "attributed_frame_id": r.frame_id,
            "frame_order": r.frame_order,
        }
        if isinstance(keyword_signal, dict):
            bundle_payload["keyword_signal"] = keyword_signal
        if meta.get("deployment_id"):
            bundle_payload["deployment_id"] = meta["deployment_id"]

        bundle_id = evidence_store.create_bundle(bundle_payload)
        bundle_ids.append(bundle_id)

    # 6. Write RCA_ATTRIBUTED (atomic)
    batch: list[tuple[str, dict[str, Any]]] = []
    graph_writer.supersede_prior_attributions(anomaly_id, run_id, _batch=batch)

    for i, r in enumerate(ranked):
        if i < len(bundle_ids):
            graph_writer.write_rca_attributed(
                anomaly_id,
                r.frame_id,
                run_id,
                "deterministic",
                r.capped_score if r.capped_score is not None else r.score,
                "candidate",
                bundle_ids[i],
                decision_ts,
                _batch=batch,
            )

    graph_writer.write_atomic(batch)

    return RCARunResult(
        run_id=run_id,
        anomaly_id=anomaly_id,
        attribution_count=len(ranked),
        bundle_ids=bundle_ids,
        confidence_assessments=confidence_assessments,
        ranked_candidates=[
            {
                "file_id": r.file_id,
                "path": r.path,
                "ranking_score": r.capped_score if r.capped_score is not None else r.score,
            }
            for r in ranked
        ],
    )


class RCARunResult:
    """Result of an RCA run."""

    def __init__(
        self,
        run_id: str,
        anomaly_id: str,
        attribution_count: int,
        bundle_ids: list[str],
        confidence_assessments: list[dict[str, Any]] | None = None,
        ranked_candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        self.run_id = run_id
        self.anomaly_id = anomaly_id
        self.attribution_count = attribution_count
        self.bundle_ids = bundle_ids
        self.confidence_assessments = confidence_assessments or []
        self.ranked_candidates = ranked_candidates or []
