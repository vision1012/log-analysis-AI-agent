# RCA Evaluation Metrics — Deterministic RCA v1

Evaluation metrics for deterministic RCA v1. Ground truth from human feedback. No LLM. All metrics computed from graph state and RCA_ATTRIBUTED status.

---

## 1. Ground Truth and Labels

### Ground Truth: Accepted Edges Only

| Source | Rule |
|--------|------|
| **Positive label** | RCA_ATTRIBUTED with status=accepted. Human confirmed this attribution as root cause. |
| **Scope** | Per anomaly, at most one accepted. The accepted attribution's target (StackFrame → File via IN_FILE) is the ground-truth root cause file. |
| **Identity** | Ground truth = attributed_file_id (File node) of the accepted attribution. |

**Rule:** For evaluation, an anomaly has ground truth only when it has exactly one RCA_ATTRIBUTED with status=accepted. Anomalies with no accepted attribution are excluded from precision/MRR (or treated as "no correct answer" for MRR).

### Negative Labels: Rejected Edges

| Source | Rule |
|--------|------|
| **Negative label** | RCA_ATTRIBUTED with status=rejected. Human said "not the root cause." |
| **Scope** | Per anomaly, zero or more rejected. Each rejected attribution's target File is a negative example. |
| **Use** | For False Acceptance Rate: attributions that were proposed (candidate) but human rejected. For precision: an attribution is incorrect if it was rejected or if human accepted a different one. |

### Evaluation Scope

| Condition | Inclusion |
|-----------|------------|
| Anomaly has accepted attribution | Include in evaluation. Ground truth = accepted File. |
| Anomaly has rejected attributions only | Include for FAR (negative labels). Exclude from Precision@1/MRR if no ground truth. |
| Anomaly has only candidates (no feedback) | Exclude. No ground truth yet. |
| Anomaly has superseded | Use most recent run; superseded are historical. |

---

## 2. Precision@1

### Definition

Among anomalies with ground truth, what fraction have the correct attribution at rank 1?

### Computation

| Step | Action |
|------|--------|
| 1 | Select anomalies with exactly one RCA_ATTRIBUTED status=accepted. |
| 2 | For each anomaly, obtain the RCA run that produced the accepted attribution (or the run that produced the top-3 candidates before human confirmed). |
| 3 | Rank the candidates by score (as at attribution time). Rank 1 = highest score. |
| 4 | **Correct@1:** Rank-1 candidate's File = accepted File. |
| 5 | **Precision@1** = |anomalies with correct@1| / |anomalies with ground truth|. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter anomalies by Anomaly.service_ref. Compute Precision@1 over that subset. |
| **Aggregate** | Global = weighted average by service volume, or per-service reported separately. |

### Without LLM

Compare attributed_file_id (or File.id) of rank-1 candidate to attributed_file_id of accepted attribution. Exact match. No semantic similarity.

---

## 3. Precision@3

### Definition

Among anomalies with ground truth, what fraction have the correct attribution somewhere in the top 3?

### Computation

| Step | Action |
|------|--------|
| 1 | Select anomalies with exactly one accepted. |
| 2 | For each anomaly, obtain the top-3 candidates (by score) from the RCA run. |
| 3 | **Correct@3:** Accepted File appears in the top-3 candidate Files. |
| 4 | **Precision@3** = |anomalies with correct@3| / |anomalies with ground truth|. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter by service_ref. Compute Precision@3 over that subset. |

### Without LLM

Set membership: is accepted File in {rank-1 File, rank-2 File, rank-3 File}? Exact match.

---

## 4. Mean Reciprocal Rank (MRR)

### Definition

For each anomaly with ground truth, find the rank of the first correct attribution. Reciprocal rank = 1/rank. MRR = mean of reciprocal ranks across anomalies.

### Computation

| Step | Action |
|------|--------|
| 1 | Select anomalies with exactly one accepted. |
| 2 | For each anomaly, rank candidates by score. Find rank of the accepted File (1, 2, or 3). |
| 3 | **Reciprocal rank:** 1 if rank 1, 1/2 if rank 2, 1/3 if rank 3. 0 if not in top 3. |
| 4 | **MRR** = mean(reciprocal_rank) over anomalies. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter by service_ref. Compute MRR over that subset. |

### Without LLM

Exact match of File.id. No LLM.

---

## 5. False Acceptance Rate

### Definition

Among attributions that were proposed (candidate) and could have been auto-accepted (e.g. high confidence), what fraction did the human reject?

### Computation

| Step | Action |
|------|--------|
| 1 | Select RCA_ATTRIBUTED attributions with status=rejected that were candidates (proposed by RCA run). |
| 2 | **Optional threshold:** Restrict to attributions with confidence ≥ threshold (e.g. 0.7) to simulate "would have been auto-accepted." |
| 3 | **False acceptances:** Rejected attributions that were in top 3. |
| 4 | **FAR** = |false acceptances| / |total proposed attributions in top 3|, or = |false acceptances| / |anomalies with at least one proposed attribution|. |

### Alternative Definition

| Definition | Formula |
|------------|---------|
| **Attribution-level** | FAR = rejected attributions / total attributions (candidate + accepted). |
| **Anomaly-level** | FAR = anomalies where human rejected all top 3 / anomalies with at least one proposed attribution. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter by service_ref. Compute FAR over that subset. |

### Without LLM

Count of rejected vs accepted. No LLM.

---

## 6. Confidence Calibration Curve

### Definition

For bins of predicted confidence, compare the fraction of correct attributions to the average confidence in that bin. Well-calibrated: 60% confidence → 60% correct.

### Computation

| Step | Action |
|------|--------|
| 1 | Select anomalies with ground truth. For each, take the rank-1 candidate's confidence. |
| 2 | **Correct:** 1 if rank-1 File = accepted File; 0 otherwise. |
| 3 | **Bin confidence:** e.g. [0.2–0.3], [0.3–0.4], …, [0.8–0.9]. |
| 4 | For each bin: mean(confidence) = predicted, mean(correct) = actual accuracy. |
| 5 | **Calibration curve:** Plot predicted (x) vs actual (y). Ideal: y = x. |
| 6 | **Expected Calibration Error (ECE):** Weighted average of |predicted − actual| per bin. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Filter by service_ref. Compute calibration curve over that subset. |

### Without LLM

Confidence from RCA_ATTRIBUTED.confidence. Correctness from exact File match. No LLM.

---

## 7. Signal Drift Detection

### Definition

Detect when the distribution of graph-derived signals changes over time. Drift may indicate ingestion changes, deployment correlation changes, or data quality shifts.

### Signals Monitored

| Signal | Source | Drift Risk |
|--------|--------|------------|
| trace_completeness | StackFrame.resolution | Parser or repo scope change |
| last_touch_recency | TOUCHED, Commit.timestamp | Git mining gaps |
| deploy_proximity, deploy_recency_rank, deployment_timing_valid | Deployment, DEPLOYED_COMMIT | Deployment ingestion changes |
| historical_recurrence | Prior RCA_ATTRIBUTED | Feedback volume change |
| file_frame_count | IN_FILE | Trace structure change |

### Computation (Without LLM)

| Step | Action |
|------|--------|
| 1 | **Baseline window:** Compute mean and std (or percentiles) of each signal over a reference period (e.g. last 30 days of attributions). |
| 2 | **Current window:** Compute same stats over a recent period (e.g. last 7 days). |
| 3 | **Drift metric:** Compare current to baseline. Options: (a) difference in mean beyond threshold; (b) ratio of std; (c) percentile shift; (d) statistical test (e.g. Kolmogorov-Smirnov) if sample size permits. |
| 4 | **Alert:** Flag when drift exceeds threshold for any signal. |

### Per-Service

| Scope | Computation |
|-------|-------------|
| **Per service_ref** | Compute drift per service. Different services may have different baseline distributions. |

### Without LLM

Pure statistics on signal values from evidence bundles or recomputed from graph. No LLM.

---

## 8. Summary: Metric Computation

| Metric | Ground Truth | Negative Labels | Per-Service | LLM |
|--------|--------------|-----------------|-------------|-----|
| Precision@1 | Accepted only | — | Yes | No |
| Precision@3 | Accepted only | — | Yes | No |
| MRR | Accepted only | — | Yes | No |
| FAR | — | Rejected | Yes | No |
| Calibration | Accepted | Rejected (implicit) | Yes | No |
| Signal Drift | — | — | Yes | No |

---

## 9. Evaluation Data Requirements

| Requirement | Source |
|-------------|--------|
| **RCA_ATTRIBUTED** | status, confidence, evidence_ref, attributed_at, run_id |
| **Evidence bundle** | signal_scores, attributed_file_id (for recomputation) |
| **Graph** | Anomaly.service_ref, StackFrame→File, ranking at attribution time |
| **Human feedback** | status transitions (accepted, rejected) |

All metrics are computed from graph state and stored evidence. No LLM. No external APIs.
