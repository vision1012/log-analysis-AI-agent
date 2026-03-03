# RCA Evaluation Metrics — Deterministic RCA in Hybrid Mode

Evaluation metrics for deterministic RCA v1 in Hybrid mode (auto + manual triggers). Ground truth from accepted edges. All metrics computed from graph state and RCA_ATTRIBUTED status. No LLM.

---

## 1. Ground Truth and Run Counting

### Ground Truth: Accepted Edges Only

| Source | Rule |
|--------|------|
| **Positive label** | RCA_ATTRIBUTED with status=accepted. Human confirmed this attribution as root cause. |
| **Identity** | Ground truth = attributed_file_id (File node) of the accepted attribution. |
| **Scope** | Per anomaly, at most one accepted. |

### How Manual Reruns Are Counted (Avoid Double-Counting)

| Rule | Description |
|------|-------------|
| **One evaluation unit per anomaly per accepted** | For Precision@1, Precision@3, MRR: count each anomaly at most once. Use the run that produced the accepted attribution. If human confirmed from run A, that run is the evaluation unit. |
| **Manual rerun with same idempotency key** | Returns existing result. No new run. Do not count as separate run for metrics. |
| **Manual rerun with new idempotency key** | New run. Produces new candidates. If human accepts from this run, use this run for evaluation. Prior run (if any) is superseded; do not double-count. |
| **Multiple runs before accept** | Human may reject run A, rerun (run B), then accept from run B. Evaluation uses run B only. Run A is not counted for Precision/MRR (no ground truth from A). |
| **Denominator for run-based metrics** | Total runs = distinct (run_id) that completed (wrote candidates or skipped). Exclude runs that returned existing result (idempotency hit). |

| Summary | Count each anomaly once per its accepted attribution. Count each run once (exclude idempotency hits). Do not double-count anomalies across manual reruns. |

---

## 2. Precision@1, Precision@3, MRR

### Precision@1

| Definition | Among anomalies with ground truth, what fraction have the correct attribution at rank 1? |
|------------|--------------------------------------------------------------------------------------------|
| **Formula** | |anomalies with correct@1| / |anomalies with ground truth| |
| **Correct@1** | Rank-1 candidate's File = accepted File. |
| **Ground truth** | Accepted attribution's File. |

### Precision@3

| Definition | Among anomalies with ground truth, what fraction have the correct attribution in top 3? |
|------------|--------------------------------------------------------------------------------------------|
| **Formula** | |anomalies with correct@3| / |anomalies with ground truth| |
| **Correct@3** | Accepted File appears in {rank-1, rank-2, rank-3} candidate Files. |

### Mean Reciprocal Rank (MRR)

| Definition | Mean of 1/rank of first correct attribution. Rank 1→1, rank 2→1/2, rank 3→1/3. Not in top 3→0. |
|------------|-----------------------------------------------------------------------------------------------|
| **Formula** | MRR = mean(reciprocal_rank) over anomalies with ground truth. |

### Per-Service Breakdown

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter anomalies by Anomaly.service_ref. Compute Precision@1, Precision@3, MRR over that subset. |
| **Report** | Per-service and global. |

---

## 3. Coverage Rate

### Definition

Percentage of anomalies (in scope) that received at least one candidate from an RCA run.

### Computation

| Step | Action |
|------|--------|
| 1 | **Scope:** Anomalies that had an RCA run (auto or manual) in the evaluation window. |
| 2 | **With candidates:** Anomalies where the run produced ≥ 1 RCA_ATTRIBUTED (status=candidate or accepted). |
| 3 | **Coverage rate** = |anomalies with ≥ 1 candidate| / |anomalies with RCA run| × 100%. |

### Exclusions

| Excluded | Reason |
|----------|--------|
| Pre-RCA block | Anomaly never ran RCA. Do not include in denominator. |
| No candidates (all excluded, below threshold) | Run completed but wrote 0 attributions. Include in denominator; 0 in numerator. |
| Idempotency hit (returned existing) | Do not count as new run. Use prior run's result if in scope. |

### Per-Service Breakdown

| Scope | Filter by service_ref. Compute coverage per service. |
|-------|------------------------------------------------------|

---

## 4. Acceptance Rate

### Definition

Among RCA runs that produced candidates, what fraction did the human accept (confirm) at least one candidate?

### Computation

| Step | Action |
|------|--------|
| 1 | **Total runs:** RCA runs that completed and wrote ≥ 1 candidate (RCA_ATTRIBUTED status=candidate or accepted). Exclude idempotency hits. |
| 2 | **Accepted runs:** Runs where human subsequently confirmed one candidate (status→accepted). |
| 3 | **Acceptance rate** = |runs with at least one accepted| / |total runs with candidates| × 100%. |

### Alternative: Per-Anomaly

| Definition | |anomalies with accepted| / |anomalies with ≥ 1 candidate| × 100%. |
|------------|-------------------------------------------------------------|
| **Use** | Anomaly-centric view. Each anomaly counted once. |

### Per-Service Breakdown

| Scope | Filter by service_ref. Compute acceptance rate per service. |
|-------|------------------------------------------------------------|

---

## 5. Time-to-Suggestion, Time-to-Accept

### Time-to-Suggestion

| Definition | Elapsed time from anomaly ingestion (or anomaly timestamp) until RCA run completes and writes candidates. |
|------------|--------------------------------------------------------------------------------------------------------|
| **Start** | Anomaly.created_at or Anomaly.timestamp (ingestion time). |
| **End** | RCA run completion (attributions written). attributed_at of first candidate. |
| **Metric** | Median, P95, P99 per service. |

### Time-to-Accept

| Definition | Elapsed time from first candidate written until human confirms (candidate → accepted). |
|------------|---------------------------------------------------------------------------------------|
| **Start** | attributed_at of first candidate for that anomaly. |
| **End** | Timestamp of feedback event (actor confirmed). From audit log. |
| **Metric** | Median, P95, P99 per service. Exclude anomalies with no accept (reject all, or pending). |

### Per-Service Breakdown

| Scope | Compute time-to-suggestion and time-to-accept per service_ref. |
|-------|---------------------------------------------------------------|

---

## 6. Confidence Calibration

### Definition

For bins of predicted confidence (rank-1 candidate score), compare the fraction of correct attributions to the average confidence in that bin. Well-calibrated: 60% confidence → 60% correct.

### Computation (Binning Score vs Acceptance Correctness)

| Step | Action |
|------|--------|
| 1 | Select anomalies with ground truth (human accepted). |
| 2 | For each, take rank-1 candidate's confidence at attribution time. |
| 3 | **Correct:** 1 if rank-1 File = accepted File; 0 otherwise. |
| 4 | **Bin confidence:** e.g. [0.2–0.3], [0.3–0.4], …, [0.8–0.9]. |
| 5 | For each bin: mean(confidence) = predicted; mean(correct) = actual accuracy (acceptance correctness). |
| 6 | **Calibration curve:** Plot predicted (x) vs actual (y). Ideal: y = x. |
| 7 | **Expected Calibration Error (ECE):** Weighted average of |predicted − actual| per bin. |

### Acceptance Correctness

| Term | Meaning |
|------|---------|
| **Acceptance correctness** | For rank-1 candidate: 1 if human accepted it (or accepted a different rank; then 0). Equivalently: 1 if rank-1 File = accepted File. |

### Per-Service Breakdown

| Scope | Filter by service_ref. Compute calibration per service. |
|-------|--------------------------------------------------------|

---

## 7. Drift Metrics (Per-Signal Distribution Change)

### Definition

Detect when the distribution of graph-derived signals changes over time. Per-signal drift indicates ingestion, deployment, or feedback changes.

### Signals Monitored

| Signal | Source | Drift Risk |
|--------|--------|------------|
| trace_completeness | StackFrame.resolution | Parser or repo scope change |
| last_touch_recency | TOUCHED, Commit.timestamp | Git mining gaps |
| deploy_proximity, deploy_recency_rank, deployment_timing_valid | Deployment, DEPLOYED_COMMIT | Deployment ingestion changes |
| historical_recurrence | Prior RCA_ATTRIBUTED | Feedback volume change |
| file_frame_count | IN_FILE | Trace structure change |
| top_frame, frame_depth | HAS_FRAME | Trace structure change |

### Computation

| Step | Action |
|------|--------|
| 1 | **Baseline window:** Mean, std, percentiles (P25, P50, P75) per signal over reference period (e.g. 30 days). |
| 2 | **Current window:** Same stats over recent period (e.g. 7 days). |
| 3 | **Drift metric:** Difference in mean; ratio of std; percentile shift. Or statistical test (e.g. Kolmogorov-Smirnov) if sample size permits. |
| 4 | **Alert:** Flag when drift exceeds threshold for any signal. |

### Per-Service Breakdown

| Scope | Compute drift per service_ref. Different services may have different baseline distributions. |
|-------|---------------------------------------------------------------------------------------------|

| Signal source | From evidence bundles (signal_scores) or recomputed from graph. No LLM. |

---

## 8. Summary: Metrics in Hybrid Mode

| Metric | Definition | Per-Service |
|--------|------------|-------------|
| Precision@1 | Correct@1 / anomalies with ground truth | Yes |
| Precision@3 | Correct@3 / anomalies with ground truth | Yes |
| MRR | Mean(1/rank) over anomalies with ground truth | Yes |
| Coverage rate | Anomalies with ≥ 1 candidate / anomalies with RCA run | Yes |
| Acceptance rate | Runs with accepted / runs with candidates | Yes |
| Time-to-suggestion | Median, P95, P99 from ingestion to candidates written | Yes |
| Time-to-accept | Median, P95, P99 from candidates to human confirm | Yes |
| Confidence calibration | Binning score vs acceptance correctness; ECE | Yes |
| Drift metrics | Per-signal distribution change (baseline vs current) | Yes |

---

## 9. Manual Rerun Counting Summary

| Scenario | Count for metrics |
|----------|-------------------|
| Same idempotency key, prior completed | Do not count as new run. Use prior run. |
| Same idempotency key, prior in progress | Do not count. |
| New idempotency key, new run | Count as new run. |
| Human accepted from run B (after rejecting run A) | Use run B for Precision/MRR. Run A not in denominator for acceptance rate (or count as not accepted). |
| Anomaly with one accepted | Count once for Precision/MRR. One evaluation unit. |

---

## 10. Evaluation Data Requirements

| Requirement | Source |
|-------------|--------|
| **RCA_ATTRIBUTED** | status, confidence, evidence_ref, attributed_at, run_id |
| **Evidence bundle** | signal_scores, attributed_file_id |
| **Graph** | Anomaly.service_ref, Anomaly.timestamp, Anomaly.created_at |
| **Feedback audit** | actor_id, timestamp, action (confirm, reject, rollback) |
| **Run metadata** | run_id, trigger (auto|manual), idempotency_key, completion timestamp |

All metrics computed from graph state and stored evidence. No LLM. No external APIs.
