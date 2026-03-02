# Deterministic RCA Algorithm v1

Production-ready RCA algorithm using only graph traversals and the 10 signals in `graph/confidence_signals.md`. No LLM. No code. Deterministic.

---

## 1. Candidate Generation Rules

### Input

- **Anomaly** with id, timestamp, service_ref, trace_ref
- **Scope:** Anomaly.service_ref for deployment correlation

### Traversal: Anomaly → Files

1. **Start:** Anomaly
2. **Traverse:** Anomaly -[:HAS_FRAME]-> StackFrame (ordered by frame_order)
3. **Filter:** StackFrame.resolution = `resolved` (exclude unresolved)
4. **Traverse:** StackFrame -[:IN_FILE]-> File
5. **Collect:** Distinct File nodes reached

### Candidate Set

| Rule | Description |
|------|-------------|
| **Source** | Files reachable via Anomaly → HAS_FRAME → StackFrame → IN_FILE → File |
| **Resolved only** | Only StackFrames with resolution=resolved and IN_FILE to a File |
| **Per-file aggregation** | One candidate per distinct File; each File may have multiple frames (stack positions) pointing to it |
| **Representative frame** | For scoring, use the frame with smallest frame_order (closest to top) among frames pointing to that File |

### Exclusion (Pre-Filter)

| Exclusion | Action |
|-----------|--------|
| **Unresolved files** | StackFrames with resolution=unknown have no IN_FILE; they never produce File candidates. Excluded by design. |
| **Vendor/stdlib** | Files whose path matches exclusion patterns (see Guardrails) are removed from candidate set before scoring. |
| **Cap** | After exclusions, if candidate count exceeds cap (default 20), apply tie-breaker to retain top N (see Guardrails). |

### Empty Candidate Set

| Condition | Action |
|----------|--------|
| All frames unresolved | No candidates. Block RCA; do not write attribution. Per I2: entire trace unresolved = reject or quarantine. |
| All candidates excluded (vendor/stdlib) | No candidates. Block RCA; do not write attribution. |
| Partial trace (some resolved) | Proceed with resolved frames only; trace_completeness signal < 1; confidence degraded. |

---

## 2. Scoring Model

### Per-Candidate Score

For each candidate (File, representative_frame):

```
score = Σ (weight_i × signal_i)   for i in 1..10
```

All signals in [0, 1]. Weights sum to 1.0. Default weights:

| # | Signal | Default Weight | Notes |
|---|--------|----------------|-------|
| 1 | top_frame | 0.20 | Top frame is strongest indicator |
| 2 | frame_depth | 0.10 | Depth in stack |
| 3 | last_touch_recency | 0.15 | Recency of file change |
| 4 | deploy_proximity | 0.12 | Deployment timing |
| 5 | deploy_recency_rank | 0.08 | Most recent deploy |
| 6 | historical_recurrence | 0.10 | Prior attributions |
| 7 | trace_completeness | 0.08 | Full vs partial trace |
| 8 | path_exclusion | 0.05 | Application vs vendor (0 or 1) |
| 9 | deployment_timing_valid | 0.07 | Deploy before incident |
| 10 | file_frame_count | 0.05 | Multiple frames in file |

**Total:** 1.00

### Signal Values When Unavailable

| Signal | When Unavailable | Value |
|--------|------------------|-------|
| last_touch_recency | No TOUCHED to File; no Commit | 0 |
| deploy_proximity | No Deployment; no DEPLOYED_COMMIT; Commit not deployed | 0 |
| deploy_recency_rank | Same as above | 0 |
| historical_recurrence | No prior RCA_ATTRIBUTED for this file | 0 |
| trace_completeness | Always computable from trace | 0–1 |
| path_exclusion | Always computable | 0 or 1 |
| deployment_timing_valid | No Deployment; or Deployment.timestamp ≥ Anomaly.timestamp | 0 |
| file_frame_count | Always computable | 0–1 |

### Confidence Threshold

| Threshold | Default | Purpose |
|-----------|---------|---------|
| **min_confidence** | 0.25 | Minimum weighted score to write any attribution |
| **auto_accept_threshold** | 0.70 | If top candidate ≥ this, write as accepted (optional auto-confirm) |

---

## 3. Tie-Breakers and Fallback Logic

### Tie-Breaker Order (Same Score)

When two or more candidates have the same weighted score:

| Priority | Rule | Description |
|----------|------|-------------|
| 1 | **Smallest frame_order** | Prefer the candidate whose representative frame is closer to top of stack |
| 2 | **Higher last_touch_recency** | Prefer more recently modified file |
| 3 | **Higher historical_recurrence** | Prefer file with prior attributions |
| 4 | **Lexicographic path** | Deterministic: prefer smaller File.path (string compare) |

### Fallback: Deployment Info Missing

| Condition | Behavior |
|----------|----------|
| **No Deployments** | deploy_proximity, deploy_recency_rank, deployment_timing_valid = 0. RCA proceeds with remaining 7 signals. Do not block. |
| **All deployments pending** | Same as no deployments. Exclude from correlation. |
| **Deployment exists but Commit not in graph** | Exclude that deployment; treat as missing for that candidate. |
| **service_ref mismatch** | Exclude deployment from correlation (I10). |

### Fallback: Frames Unresolved

| Condition | Behavior |
|----------|----------|
| **Partial trace** | Use only resolved frames for candidates. trace_completeness = resolved_count / total_count. Proceed; degrade confidence. |
| **Entire trace unresolved** | No candidates. Block RCA. |
| **Single frame resolved** | One candidate; score with trace_completeness < 1. |

### Fallback: No Last-Touch Commit

| Condition | Behavior |
|----------|----------|
| **File has no TOUCHED** | last_touch_recency = 0. Candidate still scored; other signals apply. |
| **Commit not in graph** | last_touch_recency = 0. |

### Fallback: No Candidates After Guardrails

| Condition | Action |
|----------|--------|
| All excluded (vendor/stdlib) | Do not write attribution. Return "no candidate" result. |
| Cap reduces to empty | Should not occur; cap applies after scoring. |

---

## 4. Output Writing Rules

### RCA_ATTRIBUTED Edge

| Property | Required | Value |
|----------|----------|-------|
| run_id | Yes | RCA run identifier (UUID/ULID) |
| method | Yes | `deterministic` |
| confidence | Yes | Final weighted score (0.0–1.0) |
| status | Yes | `candidate` or `accepted` |
| evidence_ref | Yes | Bundle ID (bundle_id) |
| attributed_at | Yes | ISO 8601 UTC |

**Direction:** Anomaly -[:RCA_ATTRIBUTED]-> StackFrame

**Target:** The representative StackFrame (smallest frame_order among frames pointing to winning File).

### When to Create RCA_ATTRIBUTED

| Condition | Action |
|----------|--------|
| Top candidate score ≥ min_confidence | Create RCA_ATTRIBUTED to representative StackFrame |
| Top candidate score < min_confidence | Do not create attribution |
| No candidates | Do not create attribution |

### Status: candidate vs accepted

| Condition | status |
|----------|--------|
| **Default** | `candidate` |
| **Auto-confirm** | If top candidate score ≥ auto_accept_threshold (default 0.70), may set `accepted` |
| **Manual confirm** | Human action; candidate → accepted (see rca_run_lifecycle.md) |

### Superseding Prior Attribution

| Rule | Description |
|------|-------------|
| **Before write** | For this Anomaly, set any existing RCA_ATTRIBUTED with status in {candidate, accepted} to status=superseded |
| **Then write** | Create new RCA_ATTRIBUTED with status=candidate (or accepted if auto-confirm) |
| **Invariant** | At most one non-superseded attribution per Anomaly (I8, I9) |

### Evidence Bundle

| Field | Source |
|-------|--------|
| bundle_id | New UUID/ULID; = evidence_ref |
| anomaly_id | Anomaly.id |
| trace_ref | Anomaly.trace_ref |
| rca_run_id | run_id |
| attributed_file_id | Winning File.id |
| attributed_frame_id | Representative StackFrame.id |
| evidence_symbol | StackFrame.symbol_name |
| last_touch_commit_sha | Commit.sha from last-touch traversal, or empty |
| signal_scores | Map of 10 signal names → values |
| method | `deterministic` |
| rule_version | `deterministic_rca_v1` |
| schema_version | Bundle contract version (e.g. 1.0.0) |
| decision_timestamp | attributed_at |
| deployment_id | Deployment.id if deployment correlation used; optional |

---

## 5. Guardrails

### Exclude Unresolved Files

| Rule | Implementation |
|------|----------------|
| **Unresolved frames** | StackFrames with resolution=unknown have no IN_FILE. They never produce File candidates. No explicit filter needed; traversal excludes them. |
| **Explicit check** | If building candidates from frames, skip frames where resolution ≠ resolved. |

### Exclude Vendor/Stdlib

| Rule | Implementation |
|------|----------------|
| **Path patterns** | Before scoring, remove from candidate set any File where path matches exclusion patterns (see confidence_signals.md). |
| **Patterns** | `node_modules/`, `vendor/`, `site-packages/`, `lib/python`, `node:internal`, `runtime.`, `java.`, `sun.`, `jdk.` (configurable). |
| **Match** | Prefix or substring match; case-sensitive for paths. |

### Cap Number of Candidates

| Rule | Implementation |
|------|----------------|
| **Default cap** | 20 candidates max before scoring |
| **When exceeded** | Apply pre-score tie-breaker: retain candidates with smallest representative frame_order first; then by path. Keep top 20. |
| **After scoring** | Select single winner (highest score; tie-breakers). Cap does not limit output; only limits how many are scored. |

### Block Conditions

| Condition | Action |
|----------|--------|
| Entire trace unresolved | Block; no RCA |
| No candidates after exclusions | Block; no attribution |
| Pre-RCA gate failures (I1, I2, I6, I8, I9) | Block run for that anomaly |

---

## 6. Algorithm Summary (Plain English)

1. **Load** Anomaly by id; verify HAS_FRAME exists.
2. **Traverse** to resolved StackFrames (IN_FILE → File).
3. **Collect** distinct Files; assign representative frame (smallest frame_order per file).
4. **Exclude** Files matching vendor/stdlib path patterns.
5. **Cap** to 20 candidates if needed (tie-break by frame_order, path).
6. **For each candidate:** Compute 10 signals via graph traversals; apply weights; sum.
7. **Select** winner: max score; tie-break by frame_order, last_touch_recency, historical_recurrence, path.
8. **If** winner score ≥ min_confidence: supersede prior attribution; create RCA_ATTRIBUTED; create evidence bundle.
9. **Set** status = accepted if score ≥ auto_accept_threshold, else candidate.

---

## 7. Determinism Guarantee

Same inputs (Anomaly, graph state) → same output (attributed_file_id, confidence, signal_scores). No randomness. No LLM. All traversals and formulas are deterministic.
