"""RCA engine: deterministic RCA runner and orchestration."""

from rca_engine.candidate_generator import Candidate, RepresentativeFrame, generate_candidates
from rca_engine.confidence_engine import (
    ConfidenceAssessment,
    build_confidence_reasoning,
    compute_confidence_assessment,
    compute_confidence_for_ranked,
)
from rca_engine.ranking_model import RankedCandidate, rank_candidates
from rca_engine.rca_runner import RCARunResult, run_deterministic_rca, run_rca
from rca_engine.signal_computation import (
    MCP_SIGNAL_NAMES,
    compute_mcp_signals,
    compute_signals,
    fetch_anomaly_context,
    fetch_file_metadata,
)

__all__ = [
    "Candidate",
    "RepresentativeFrame",
    "ConfidenceAssessment",
    "RankedCandidate",
    "RCARunResult",
    "MCP_SIGNAL_NAMES",
    "build_confidence_reasoning",
    "compute_confidence_assessment",
    "compute_confidence_for_ranked",
    "compute_mcp_signals",
    "compute_signals",
    "fetch_anomaly_context",
    "fetch_file_metadata",
    "generate_candidates",
    "rank_candidates",
    "run_deterministic_rca",
    "run_rca",
]
