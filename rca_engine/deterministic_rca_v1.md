# Deterministic RCA Engine v1 — Autonomous Debugging Platform

Production-ready RCA engine for the Autonomous Debugging platform. Graph-only signals. No LLM. Uses nodes: Anomaly, StackFrame, File, Commit, Deployment. Relationships: HAS_FRAME, IN_FILE, TOUCHED, DEPLOYED_COMMIT, RCA_ATTRIBUTED. Output top N=3 candidates only. No automatic acceptance.

---

## 1. Candidate Generation

### Traversal: Anomaly → StackFrame → File

| Step | Action |
|------|--------|
| 1 | Start at Anomaly |
| 2 | Traverse Anomaly -[:HAS_FRAME]-> StackFrame (ordered by frame_order ascending) |
| 3 | Apply frame depth cap: consider only frames with frame_order < max_depth (default 20) |
| 4 | Filter: StackFrame.resolution = resolved (exclude unresolved) |
| 5 | Traverse StackFrame -[:IN_FILE]-> File |
| 6 | Collect distinct File nodes reached |
| 7 | Assign representative frame per File: smallest frame_order among frames pointing to that File |

### Frame Depth Caps

| Parameter | Default | Max | Purpose |
|-----------|---------|-----|---------|
| **K** | 5 | 5 | Max candidates retained for scoring after exclusions |
| **max_depth** | 20 | 20 | Max frame_order to consider (0..19). Frames at depth ≥ max_depth ignored. |

**Rule:** Only frames with frame_order in [0, max_depth−1] contribute to candidate collection. Deeper frames are excluded to focus on failure-proximate code.

### Exclusion Rules

| Exclusion | Rule |
|-----------|------|
| **Unresolved** | StackFrames with resolution=unknown have no IN_FILE. Never produce File candidates. Excluded by traversal. |
| **Stdlib** | File.path matches: `lib/python`, `node:internal`, `node:internal`, `runtime.`, `java.`, `sun.`, `jdk.` |
| **Vendor** | File.path matches: `node_modules/`, `vendor/`, `site-packages/` |
| **Match** | Prefix or substring; case-sensitive. See `graph/confidence_signals.md`. |
| **When** | Apply after traversal; before cap K. |

### Deduplication Logic

| Aspect | Rule |
|--------|------|
| **Per-file** | One candidate per distinct File. Multiple StackFrames may point to same File; aggregate to single candidate. |
| **Representative frame** | For each File, use StackFrame with smallest frame_order (closest to top). |
| **Pre-score cap** | When candidate count > K after exclusions, retain top K by: (1) smallest representative frame_order, (2) lexicographic File.path. |
| **Output cap** | After scoring, output top N=3. No deduplication at output; each of top 3 is a distinct File. |

### Empty Candidate Set

| Condition | Action |
|----------|--------|
| All frames unresolved | Block RCA; do not write attribution. |
| All candidates excluded (stdlib/vendor) | Block RCA; do not write attribution. |
| No frames within max_depth | Block RCA. |
| Partial trace (some resolved) | Proceed with resolved frames only; trace_completeness < 1. |

---

## 2. Signal Computation

### How Each Signal Is Computed

All signals are graph-derived. Traversals only. No external APIs.

| # | Signal | Computation |
|---|--------|-------------|
| 1 | **top_frame** | 1 if representative frame has frame_order=0; else 0. |
| 2 | **frame_depth** | 1 − (representative_frame_order / max_order_in_scope). max_order = max frame_order among frames in scope (0..max_depth−1). Closer to top = higher. |
| 3 | **last_touch_recency** | File ← TOUCHED ← Commit. Select Commit with max(timestamp) where timestamp < Anomaly.timestamp. Normalize: 1 − (anomaly_ts − commit_ts) / decay_window. Clamp to [0,1]. Empty → 0. |
| 4 | **deploy_proximity** | Deployment → DEPLOYED_COMMIT → Commit. Find Deployment where Commit = last-touch Commit, service_ref = Anomaly.service_ref, Deployment.timestamp < Anomaly.timestamp. Normalize time delta to [0,1]. Missing → 0. |
| 5 | **deploy_recency_rank** | 1 if last-touch Commit's deployment is the most recent deployment before Anomaly.timestamp (for service_ref); else 0. Missing → 0. |
| 6 | **historical_recurrence** | Count prior RCA_ATTRIBUTED (status in {accepted, candidate}) for same File (or symbol) and same service_ref. Normalize: min(count / max_recurrence_cap, 1). None → 0. |
| 7 | **trace_completeness** | resolved_count / total_count. Count frames in scope (frame_order < max_depth) with resolution=resolved; total = all frames in scope. |
| 8 | **path_exclusion** | 1 if File.path does not match stdlib/vendor patterns; 0 if matches. Candidates after exclusion filter always have 1. |
| 9 | **deployment_timing_valid** | 1 if Deployment.timestamp < Anomaly.timestamp for correlated deployment; 0 if missing or invalid. |
| 10 | **file_frame_count** | Count of frames in trace (in scope) that have IN_FILE to this File. Normalize: count / total_frames_in_scope. Clamp to [0,1]. |

### Missing-Data Handling

| Scenario | Affected Signals | Value | Behavior |
|----------|------------------|-------|----------|
| **Deployments missing** | deploy_proximity, deploy_recency_rank, deployment_timing_valid | 0 | Proceed; do not block. |
| **All deployments pending** | Same | 0 | Exclude from correlation. |
| **Commit not in graph** | last_touch_recency | 0 | e.g. rebased/squashed. |
| **File has no TOUCHED** | last_touch_recency | 0 | |
| **Incomplete trace** | trace_completeness | resolved/total | Proceed; confidence capped (see Guardrails). |
| **No prior attributions** | historical_recurrence | 0 | |
| **service_ref mismatch** | deploy signals | 0 | Exclude that deployment. |

### Score Normalization Rules

| Rule | Description |
|------|-------------|
| **Per-signal range** | All signals output in [0, 1]. |
| **last_touch_recency** | Use decay window (e.g. 7 days). Older commits → lower score. Linear or exponential decay. |
| **historical_recurrence** | Cap count (e.g. 5) before normalizing to avoid one file dominating. |
| **file_frame_count** | Normalize by trace length (frames in scope). |
| **Clamping** | Any computed value outside [0, 1] is clamped. |

---

## 3. Weighted Scoring Model

### Safe Default Weights

| # | Signal | Weight | Rationale |
|---|--------|--------|------------|
| 1 | top_frame | 0.15 | Strong indicator; not dominant |
| 2 | frame_depth | 0.10 | Depth in stack |
| 3 | last_touch_recency | 0.12 | Often available |
| 4 | deploy_proximity | 0.10 | Often missing |
| 5 | deploy_recency_rank | 0.08 | Often missing |
| 6 | historical_recurrence | 0.10 | Prior attributions |
| 7 | trace_completeness | 0.10 | Full vs partial trace |
| 8 | path_exclusion | 0.05 | Binary; candidates already filtered |
| 9 | deployment_timing_valid | 0.10 | Often missing |
| 10 | file_frame_count | 0.10 | Multiple frames in file |

**Total:** 1.00. No single signal > 0.15.

### Fallback Weight Redistribution

When a signal is unavailable (value forced to 0), its weight is redistributed to available signals to keep total effective weight at 1.0.

| Rule | Description |
|------|-------------|
| **Unavailable signals** | last_touch_recency, deploy_proximity, deploy_recency_rank, deployment_timing_valid when data missing. |
| **Redistribution** | Distribute unavailable weight proportionally to available signals. Example: if deploy signals (4,5,9) unavailable, their combined weight 0.28 is redistributed to signals 1,2,3,6,7,8,10 by their relative weights. |
| **Proportional** | Available signal i gets: weight_i + (weight_i / sum_available_weights) × sum_unavailable_weights. |
| **All available** | No redistribution; use nominal weights. |

### Confidence Aggregation Formula (Plain English)

For each candidate: multiply each signal value by its (possibly redistributed) weight, then sum. The result is the confidence score. If weight redistribution was applied, the sum of (redistributed_weight × signal) equals the score. All signals contribute when available; when unavailable, their weight is spread to others so the total score remains comparable across candidates with different data availability.

---

## 4. Ranking and Tie-Breakers

### Primary Ranking

Descending by weighted confidence score.

### Deterministic Tie-Breaker Order

When two or more candidates have the same score:

| Priority | Rule |
|----------|------|
| 1 | Smallest representative frame_order (closer to top of stack) |
| 2 | Higher last_touch_recency |
| 3 | Higher historical_recurrence |
| 4 | Lexicographic File.path (ascending) |

### Output Selection

Select top N=3 from ranked list. Include only candidates with score ≥ min_confidence (default 0.25). If fewer than 3 qualify, output all that qualify. If none qualify, output none.

---

## 5. Output Rules

### Write Top N=3 as status=candidate Only

| Rule | Description |
|------|-------------|
| **Count** | Up to N=3 RCA_ATTRIBUTED edges per Anomaly |
| **Status** | All written with status=candidate. No automatic acceptance. |
| **Target** | Each edge: Anomaly -[:RCA_ATTRIBUTED]-> StackFrame (representative frame for that File) |
| **Order** | Rank 1, 2, 3 by score (tie-breakers applied) |

### Required Properties on RCA_ATTRIBUTED Edge

| Property | Required | Value |
|----------|----------|-------|
| run_id | Yes | RCA run identifier (UUID/ULID) |
| method | Yes | `deterministic` |
| confidence | Yes | Weighted score (0.0–1.0); may be capped per Guardrails |
| status | Yes | `candidate` (always) |
| evidence_ref | Yes | Bundle ID (bundle_id) |
| attributed_at | Yes | ISO 8601 UTC |

### Idempotency Behavior

| Scenario | Behavior |
|----------|----------|
| **Same anomaly, same graph state, rerun** | Same run_id if idempotency key supplied; same candidates, scores, ranking. Supersede prior attributions; write same top 3. |
| **Superseding** | Before write, set any existing RCA_ATTRIBUTED with status in {candidate, accepted} to status=superseded for this Anomaly. |
| **Dedupe** | One RCA_ATTRIBUTED per (Anomaly, StackFrame, run_id). Same run_id + same anomaly + same proposed attributions → skip duplicate writes. |
| **Evidence bundle** | One per attribution. evidence_ref = bundle_id. Idempotent: same inputs → same bundle content. |

---

## 6. Guardrails

### Max Candidates

| Guardrail | Value | Purpose |
|-----------|-------|---------|
| **Pre-score cap (K)** | 5 | Max candidates scored. Reduces compute; focuses on most likely. |
| **Output cap (N)** | 3 | Max RCA_ATTRIBUTED edges written. Human reviews top 3 only. |

### Exclude Unresolved Files

| Guardrail | Rule |
|-----------|------|
| **Unresolved frames** | StackFrames with resolution=unknown have no IN_FILE. Excluded by traversal. No File candidates from them. |
| **Explicit filter** | When building candidates, skip frames where resolution ≠ resolved. |
| **Entire trace unresolved** | Block RCA. No attribution. |

### Cap Confidence If Trace Completeness Low

| Guardrail | Rule |
|-----------|------|
| **Condition** | When trace_completeness < threshold (e.g. 0.8), cap the final confidence score. |
| **Formula** | capped_confidence = min(raw_score, trace_completeness × max_confidence_when_partial). Example: max_confidence_when_partial = 0.7. If trace_completeness = 0.5, cap = 0.35. |
| **Purpose** | Avoid high confidence when trace is incomplete; partial trace implies uncertain evidence. |
| **When** | Apply after weighted sum; before ranking and output. |

### Block Conditions

| Condition | Action |
|----------|--------|
| Entire trace unresolved | Block RCA; no attribution |
| No candidates after exclusions | Block RCA; no attribution |
| Pre-RCA gate failures | Block run for that anomaly |

---

## 7. Algorithm Summary (Plain English)

1. Load Anomaly; verify HAS_FRAME exists.
2. Traverse Anomaly → HAS_FRAME → StackFrame (frame_order < max_depth, resolution=resolved) → IN_FILE → File.
3. Collect distinct Files; assign representative frame (smallest frame_order per File).
4. Exclude Files matching stdlib/vendor path patterns.
5. Cap to K candidates (tie-break by frame_order, path).
6. For each candidate: compute 10 signals; apply missing-data fallbacks; normalize.
7. Apply weight redistribution if any signals unavailable.
8. Compute weighted sum; apply confidence cap if trace_completeness low.
9. Rank by score; apply tie-breakers.
10. Select top N=3 with score ≥ min_confidence.
11. Supersede prior attributions for this Anomaly.
12. Write up to 3 RCA_ATTRIBUTED edges, each status=candidate; create evidence bundle per attribution.

---

## 8. Parameters Summary

| Parameter | Value | Purpose |
|-----------|-------|---------|
| K | 5 | Max candidates to score |
| max_depth | 20 | Max frame_order to consider (0..19) |
| N | 3 | Max RCA_ATTRIBUTED edges to write |
| min_confidence | 0.25 | Minimum score to include in output |
| status | candidate | All attributions; no auto-accept |
| trace_completeness_cap_threshold | 0.8 | Below this, cap confidence |
| max_confidence_when_partial | 0.7 | Cap multiplier when trace incomplete |

---

## 9. Determinism Guarantee

Same inputs (Anomaly, graph state) → same output (attributed files, confidence scores, signal_scores, ranking). No randomness. No LLM. All traversals and formulas are deterministic.
