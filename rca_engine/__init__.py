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
    KEYWORD_ALIGNMENT_SIGNAL,
    MCP_SIGNAL_NAMES,
    KeywordSignal,
    align_keyword_signal_for_path,
    compute_log_keyword_signal,
    compute_mcp_signals,
    compute_signals,
    extract_keyword_signals,
    fetch_anomaly_context,
    fetch_file_metadata,
)

__all__ = [
    "Candidate",
    "RepresentativeFrame",
    "ConfidenceAssessment",
    "RankedCandidate",
    "RCARunResult",
    "KEYWORD_ALIGNMENT_SIGNAL",
    "KeywordSignal",
    "MCP_SIGNAL_NAMES",
    "align_keyword_signal_for_path",
    "build_confidence_reasoning",
    "compute_confidence_assessment",
    "compute_confidence_for_ranked",
    "compute_log_keyword_signal",
    "compute_mcp_signals",
    "compute_signals",
    "extract_keyword_signals",
    "fetch_anomaly_context",
    "fetch_file_metadata",
    "generate_candidates",
    "rank_candidates",
    "run_deterministic_rca",
    "run_rca",
]
