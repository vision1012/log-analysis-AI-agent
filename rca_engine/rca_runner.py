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
from rca_engine.ranking_model import RankedCandidate, rank_candidates
from rca_engine.signal_computation import CandidateSignals, compute_signals


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
    candidate_signals, ctx = compute_signals(
        graph_client,
        anomaly_id,
        candidates,
        max_depth=max_depth,
        excluded_deployment_ids=gate_result.excluded_deployment_ids,
    )
    if len(candidate_signals) != len(candidates):
        return None

    # 4. Ranking
    ranked = rank_candidates(
        candidates,
        [cs.scores for cs in candidate_signals],
        min_confidence=min_confidence,
        top_n=top_n,
    )
    if not ranked:
        return None

    # Build file_id -> CandidateSignals for bundle metadata
    sig_by_file = {
        candidates[i].file_id: candidate_signals[i]
        for i in range(len(candidates))
    }
    cand_by_file = {c.file_id: c for c in candidates}

    # 5. Bundle-first: create and persist evidence bundles
    trace_ref = ctx.get("trace_ref") or ""
    decision_ts = datetime.now(timezone.utc).isoformat()
    bundle_ids: list[str] = []

    for r in ranked:
        cs = sig_by_file.get(r.file_id)
        c = cand_by_file.get(r.file_id)
        if not cs or not c:
            continue

        bundle_payload: dict[str, Any] = {
            "anomaly_id": anomaly_id,
            "trace_ref": trace_ref,
            "rca_run_id": run_id,
            "method": "deterministic",
            "attributed_file_id": r.file_id,
            "evidence_symbol": c.symbol_name or "",
            "last_touch_commit_sha": cs.last_commit_sha or "",
            "signal_scores": r.signal_scores,
            "decision_timestamp": decision_ts,
            "schema_version": "1.0.0",
            "attributed_frame_id": r.frame_id,
            "frame_order": r.frame_order,
        }
        if cs.deployment_id:
            bundle_payload["deployment_id"] = cs.deployment_id

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
    )


class RCARunResult:
    """Result of an RCA run."""

    def __init__(
        self,
        run_id: str,
        anomaly_id: str,
        attribution_count: int,
        bundle_ids: list[str],
    ) -> None:
        self.run_id = run_id
        self.anomaly_id = anomaly_id
        self.attribution_count = attribution_count
        self.bundle_ids = bundle_ids
