# GraphRAG Context Contract

Defines the exact structured context passed to the LLM explanation layer for graph-based RCA.

## Purpose

Provide a compact, deterministic, graph-grounded payload that is sufficient to explain RCA outcomes without exposing raw logs or proprietary code.

## Required Top-Level Fields

- `schema_version` (string): Contract version, e.g. `1.0.0`.
- `anomaly_id` (string): Unique anomaly identifier.
- `trace_ref` (string): Trace/session reference for the anomaly.
- `run_id` (string): RCA run identifier for the selected explanation context.
- `generated_at` (string): ISO-8601 timestamp for when context was packed.
- `candidates` (array): Top deterministic RCA candidates (ordered, bounded).

## Candidate Object (Required Fields)

Each candidate entry MUST include:

- `rank` (integer): 1-based rank in deterministic order.
- `file_id` (string): Attributed file identifier.
- `path` (string): File path (repo-relative if available).
- `confidence` (number): Final candidate confidence in `[0,1]`.
- `raw_score` (number): Uncapped weighted score.
- `capped_score` (number): Post-cap score used for ranking.
- `evidence_ref` (string): Pointer to persisted evidence bundle (`bundle_id`).
- `signal_summary` (array): Compact graph-derived signal list.
- `commit_deployment_evidence` (object): Last-touch commit and deployment linkage.
- `historical_recurrence_evidence` (object): Prior attribution evidence.

## `signal_summary` Entry

Each signal item MUST include:

- `name` (string): Signal name.
- `score` (number): Normalized signal score in `[0,1]`.
- `weight_used` (number): Effective weight used during scoring.

Recommended set includes (when available): top-frame/depth signal, recency signal, deployment proximity signal, recurrence signal, completeness signal.

## `commit_deployment_evidence` Object

Must include:

- `last_touch_commit_sha` (string or empty string)
- `deployment_id` (string or empty string)
- `deployment_timing_valid` (boolean)
- `is_most_recent_deployment` (boolean)

## `historical_recurrence_evidence` Object

Must include:

- `prior_count` (integer): Count of prior relevant attributed anomalies.
- `normalized_score` (number): Recurrence score used in ranking.
- `service_scope` (string or empty string): Service boundary used for recurrence lookup.

## Deterministic Ordering Rules

1. `candidates` ordered by:
   - `capped_score` descending
   - `frame_order` ascending (if available)
   - `last_touch_recency` descending (if available)
   - `historical_recurrence` descending (if available)
   - `path` ascending
2. `signal_summary` ordered by:
   - `score` descending
   - `name` ascending as tie-breaker

## Token-Efficiency Rules

- Include only top `N` candidates (default `N <= 3`).
- Include only top `M` signals per candidate (default `M <= 6`).
- Keep per-candidate text fields short and factual.
- Exclude redundant fields derivable from others.

## Data Minimization and Safety Rules

- No raw logs unless strictly required for explanation quality and explicitly enabled.
- No proprietary full-code blobs.
- No stacktrace bodies by default.
- Prefer IDs, scores, and compact metadata over verbose text.

## Evidence Pointer Requirements

- Every candidate MUST have a valid `evidence_ref`.
- `evidence_ref` MUST map to a persisted bundle in evidence storage.
- Explanations must cite evidence via these pointers, not by embedding large source payloads.

## Validation Requirements

A context payload is valid only if:

- all required top-level fields are present,
- at least one candidate exists,
- each candidate includes all required evidence sections,
- ordering rules are respected,
- token-efficiency and data-minimization constraints are satisfied.
