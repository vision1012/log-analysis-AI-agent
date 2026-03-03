# Deterministic RCA Engine v1

Production-ready RCA engine using only graph traversals and the 10 signals in `graph/confidence_signals.md`. No LLM. No code. Deterministic.

---

## 1. Candidate Generation Rules

### Traversal: Anomaly → StackFrame → File

| Step | Action |
|------|--------|
| 1 | Start at Anomaly |
| 2 | Traverse Anomaly -[:HAS_FRAME]-> StackFrame (ordered by frame_order ascending) |
| 3 | **max_depth=20:** Consider only frames with frame_order < 20 (top 20 frames of stack) |
| 4 | Filter: StackFrame.resolution = `resolved` (exclude unresolved) |
| 5 | Traverse StackFrame -[:IN_FILE]-> File |
| 6 | Collect distinct File nodes reached |

### Candidate Set

| Rule | Description |
|------|-------------|
| **Source** | Files reachable via Anomaly → HAS_FRAME → StackFrame → IN_FILE → File |
| **Depth limit** | Only frames with frame_order in [0, 19] contribute. Frames at depth ≥ 20 are ignored. |
| **Resolved only** | StackFrames with resolution=unknown have no IN_FILE; excluded by design. |
| **Per-file aggregation** | One candidate per distinct File; representative frame = smallest frame_order among frames pointing to that File |
| **Cap K=5** | After exclusions, retain at most K=5 candidates for scoring. Apply pre-score tie-breaker (see Ranking). |

### Empty Candidate Set

| Condition | Action |
|----------|--------|
| All frames unresolved | No candidates. Block RCA; do not write attribution. |
| All candidates excluded (stdlib/vendor) | No candidates. Block RCA; do not write attribution. |
| No frames within max_depth | No candidates. Block RCA. |
| Partial trace (some resolved) | Proceed with resolved frames only; trace_completeness < 1. |

---

## 2. Exclusion Rules

### Unresolved

| Rule | Implementation |
|------|----------------|
| **StackFrame.resolution=unknown** | No IN_FILE; never produces File candidates. Excluded by traversal. |
| **Explicit filter** | When building candidates, skip frames where resolution ≠ resolved. |

### Stdlib / Vendor

| Rule | Implementation |
|------|----------------|
| **Path patterns** | Remove from candidate set any File whose path matches exclusion patterns. |
| **Patterns** | `node_modules/`, `vendor/`, `site-packages/`, `lib/python`, `node:internal`, `node:internal`, `runtime.`, `java.`, `sun.`, `jdk.` |
| **Match** | Prefix or substring; case-sensitive. See `graph/confidence_signals.md`. |
| **When** | Apply before scoring; before cap K=5. |

### Order of Operations

1. Traverse (max_depth=20, resolved only) → collect Files
2. Exclude stdlib/vendor paths
3. Cap to K=5 (pre-score tie-breaker)
4. Score remaining candidates

---

## 3. Scoring Model

### Per-Candidate Score

```
score = Σ (weight_i × signal_i)   for i in 1..10
```

All signals in [0, 1]. Weights sum to 1.0.

### Initial Safe Weights

| # | Signal | Weight | Rationale |
|---|--------|--------|------------|
| 1 | top_frame | 0.15 | Strong indicator; not dominant |
| 2 | frame_depth | 0.10 | Depth in stack |
| 3 | last_touch_recency | 0.12 | Often available; moderate |
| 4 | deploy_proximity | 0.10 | Often missing; moderate |
| 5 | deploy_recency_rank | 0.08 | Often missing |
| 6 | historical_recurrence | 0.10 | Prior attributions |
| 7 | trace_completeness | 0.10 | Full vs partial trace |
| 8 | path_exclusion | 0.05 | Binary; candidates already filtered |
| 9 | deployment_timing_valid | 0.10 | Often missing; moderate |
| 10 | file_frame_count | 0.10 | Multiple frames in file |

**Total:** 1.00

**Safe design:** No single signal > 0.15. Deployment signals (4, 5, 9) sum to 0.28; when deployment data is missing, remaining signals still drive ranking.

---

## 4. Missing-Data Fallbacks

### Deployment Missing

| Condition | Behavior |
|----------|----------|
| **No deployments** | deploy_proximity, deploy_recency_rank, deployment_timing_valid = 0. Proceed with remaining 7 signals. Do not block. |
| **All deployments pending** | Same as no deployments. Exclude from correlation. |
| **service_ref mismatch** | Exclude that deployment from correlation (I10). |
| **Deployment exists but Commit not in graph** | Exclude that deployment; treat as missing for that candidate. |

### Commit Missing

| Condition | Behavior |
|----------|----------|
| **File has no TOUCHED** | last_touch_recency = 0. Candidate still scored. |
| **Commit not in graph** | last_touch_recency = 0. (e.g. rebased/squashed) |
| **Last-touch query returns empty** | last_touch_recency = 0. |

### Incomplete Trace

| Condition | Behavior |
|----------|----------|
| **Partial trace** | Use only resolved frames. trace_completeness = resolved_count / total_count. Proceed; confidence degraded. |
| **Entire trace unresolved** | No candidates. Block RCA. |
| **Frames beyond max_depth** | Ignored; not counted in trace_completeness denominator. trace_completeness = resolved_in_depth / total_in_depth. |
| **Single frame resolved** | One candidate; trace_completeness < 1. |

### Summary: Signal Values When Unavailable

| Signal | When Unavailable | Value |
|--------|------------------|-------|
| last_touch_recency | No TOUCHED; no Commit | 0 |
| deploy_proximity | No Deployment; Commit not deployed | 0 |
| deploy_recency_rank | Same | 0 |
| deployment_timing_valid | No Deployment; or Deployment.timestamp ≥ Anomaly.timestamp | 0 |
| historical_recurrence | No prior RCA_ATTRIBUTED for file | 0 |
| trace_completeness | Always computable | 0–1 |
| path_exclusion | Always computable (1 for candidates after exclusion filter) | 1 |
| top_frame, frame_depth, file_frame_count | Always computable from trace | 0–1 |

---

## 5. Ranking and Tie-Breakers

### Ranking Order

1. **Primary:** Descending weighted score
2. **Tie-breaker (same score):**
   - 1. Smallest representative frame_order (closer to top)
   - 2. Higher last_touch_recency
   - 3. Higher historical_recurrence
   - 4. Lexicographic File.path (ascending)

### Pre-Score Cap (K=5)

When candidate count exceeds K=5 after exclusions, retain top 5 by:

1. Smallest representative frame_order
2. Lexicographic File.path

### Output Selection

After scoring and ranking: select **top N=3** candidates for output. If fewer than 3 candidates exist, output all. If all have score below min_confidence (default 0.25), output none.

---

## 6. Output Rules

### Write Top N=3 as status=candidate Only

| Rule | Description |
|------|-------------|
| **Count** | Write up to N=3 RCA_ATTRIBUTED edges per Anomaly |
| **Status** | All written with status=candidate. No auto-accept. |
| **Target** | Each edge: Anomaly -[:RCA_ATTRIBUTED]-> StackFrame (representative frame for that File) |
| **Order** | Rank 1, 2, 3 by score (tie-breakers applied) |

### RCA_ATTRIBUTED Edge Properties

| Property | Value |
|----------|-------|
| run_id | RCA run identifier (UUID/ULID) |
| method | `deterministic` |
| confidence | Weighted score (0.0–1.0) |
| status | `candidate` (always) |
| evidence_ref | Bundle ID (bundle_id) |
| attributed_at | ISO 8601 UTC |

### When to Write

| Condition | Action |
|----------|--------|
| ≥ 1 candidate with score ≥ min_confidence | Write top min(3, count) attributions; each with own evidence bundle |
| All candidates < min_confidence | Do not write |
| No candidates | Do not write |

### Superseding Prior Attribution

| Rule | Description |
|------|-------------|
| **Before write** | For this Anomaly, set any existing RCA_ATTRIBUTED with status in {candidate, accepted} to status=superseded |
| **Then write** | Create up to 3 new RCA_ATTRIBUTED edges, each status=candidate |
| **Invariant note** | Multi-candidate mode allows multiple candidates per anomaly; I8 may require relaxation for this engine. |

### Evidence Bundle (Per Attribution)

One bundle per RCA_ATTRIBUTED edge. Fields: bundle_id, anomaly_id, trace_ref, rca_run_id, attributed_file_id, attributed_frame_id, evidence_symbol, last_touch_commit_sha, signal_scores, method=`deterministic`, rule_version=`deterministic_rca_v1`, schema_version, decision_timestamp, deployment_id (optional).

---

## 7. Algorithm Summary (Plain English)

1. **Load** Anomaly; verify HAS_FRAME exists.
2. **Traverse** Anomaly → HAS_FRAME → StackFrame (frame_order < 20, resolution=resolved) → IN_FILE → File.
3. **Collect** distinct Files; assign representative frame (smallest frame_order per file).
4. **Exclude** Files matching stdlib/vendor path patterns.
5. **Cap** to K=5 candidates (tie-break by frame_order, path).
6. **Score** each candidate: compute 10 signals; apply weights; sum.
7. **Rank** by score; apply tie-breakers.
8. **Select** top N=3 with score ≥ min_confidence.
9. **Supersede** prior attributions for this Anomaly.
10. **Write** up to 3 RCA_ATTRIBUTED edges, each status=candidate; create evidence bundle per attribution.

---

## 8. Parameters Summary

| Parameter | Value | Purpose |
|-----------|-------|---------|
| K | 5 | Max candidates to score |
| max_depth | 20 | Max frame_order to consider (0..19) |
| N | 3 | Max RCA_ATTRIBUTED edges to write |
| min_confidence | 0.25 | Minimum score to include in output |
| status | candidate | All attributions; no auto-accept |

---

## 9. Determinism Guarantee

Same inputs (Anomaly, graph state) → same output (attributed files, confidence scores, signal_scores, ranking). No randomness. No LLM. All traversals and formulas are deterministic.
