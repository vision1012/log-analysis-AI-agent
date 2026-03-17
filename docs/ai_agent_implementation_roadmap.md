# RCA Platform Roadmap (Current Focus)

This roadmap aligns to the active graph-based RCA platform, not the archived legacy agent pipeline.

## Current Active Baseline

- Deterministic RCA execution (`pre gate -> candidates -> signals -> ranking -> evidence -> atomic attributions`)
- RCA API routes (`run`, `rerun`, `results`, `result-view`, `run-status`)
- Feedback API routes (`confirm`, `reject`, `reject-all`, `rollback`)
- Evidence bundle creation and graph reference linking
- Locking/idempotency and rerun supersede behavior

## Near-Term Priorities

1. **RCA correctness hardening**
   - Add regression fixtures for signals/ranking edge cases
   - Strengthen gate and idempotency test coverage

2. **Operational reliability**
   - Improve observability around run lifecycle and gate outcomes
   - Expand smoke coverage for partial graph/deployment data

3. **API contract maturity**
   - Standardize response/error payload shape across RCA and feedback endpoints
   - Clarify versioning expectations in API docs

4. **Evaluation automation**
   - Automate recurring metrics from `evaluation/rca_metrics.md`
   - Track precision/coverage trends over accepted attributions

5. **Ingestion quality**
   - Continue improving deployment/commit linkage quality
   - Harden backfill and late-data behavior

## Medium-Term Direction

- Policy refinements (confidence thresholds, optional auto-accept constraints)
- Reviewer workflow UX support (without changing deterministic core guarantees)
- ML-assisted feature inputs where deterministic policy remains authoritative

## Legacy Note

Legacy log-agent/RAG roadmap content is archived in `old_log_arch_v1/docs/` and is not the active architecture plan.
