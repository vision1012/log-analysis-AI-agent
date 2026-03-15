"""RCA engine: deterministic RCA runner and orchestration."""

from rca_engine.candidate_generator import Candidate, RepresentativeFrame, generate_candidates
from rca_engine.ranking_model import RankedCandidate, rank_candidates
from rca_engine.rca_runner import RCARunResult, run_deterministic_rca, run_rca
from rca_engine.signal_computation import (
    compute_signals,
    fetch_anomaly_context,
    fetch_file_metadata,
)

__all__ = [
    "Candidate",
    "RepresentativeFrame",
    "RankedCandidate",
    "RCARunResult",
    "compute_signals",
    "fetch_anomaly_context",
    "fetch_file_metadata",
    "generate_candidates",
    "rank_candidates",
    "run_deterministic_rca",
    "run_rca",
]
