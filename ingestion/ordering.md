# Ingestion Ordering — Constraints and Event-Time Semantics

Ordering constraints, event-time semantics, watermark strategy, and clock skew handling for deterministic RCA.

---

## 1. Ingestion Ordering Constraints

### Hard Dependencies

| Order | Source | Must Complete Before |
|-------|--------|---------------------|
| 1 | **Git** | Logs (Files must exist for StackFrame→IN_FILE) |
| 2 | **Logs** | RCA run (Anomaly + StackFrames + IN_FILE must exist) |
| 3 | **Deployments** | RCA deployment correlation (optional; Commits must exist for DEPLOYED_COMMIT) |

### Dependency Graph

```
Git (Commit, File, TOUCHED)
    │
    ├──► Logs (Anomaly, StackFrame, HAS_FRAME, IN_FILE)  [requires File]
    │
    └──► Deployments (Deployment, DEPLOYED_COMMIT)  [requires Commit]
```

### Minimum Order for RCA

Before RCA can run for an anomaly set:

1. **Git** must have synced all Commits and Files in the repo_ref scope used by the anomaly's frames.
2. **Logs** must have ingested the Anomaly with at least one HAS_FRAME; at least one StackFrame must have IN_FILE (partial trace allowed; entire trace unresolved blocks).
3. **Deployments** (optional) must have ingested Deployments with DEPLOYED_COMMIT for the service_ref and time range of interest; Commits must exist.

---

## 2. Event-Time Semantics

### Event Time vs Ingest Time

| Field | Meaning | Use |
|-------|---------|-----|
| **timestamp** | When the event occurred (domain time from source) | RCA correlation, ordering, time-range queries |
| **created_at** | When the record was written to the graph | Audit, idempotency, ingestion ordering |

**Rule:** All RCA logic uses `timestamp` (event time). Ingest order and `created_at` do not affect RCA decisions.

### Source-Specific Event Time

| Source | Event Time Field | Semantics |
|--------|------------------|-----------|
| Logs | Anomaly.timestamp | When the anomaly/symptom occurred |
| Git | Commit.timestamp | When the commit was authored (or committed) |
| Deployments | Deployment.timestamp | When the deployment completed |

---

## 3. What Can Arrive Out of Order

### Tolerated Out-of-Order

| Scenario | Behavior |
|----------|----------|
| **Deployment before Commit** | Create Deployment with backfill_status=pending; add DEPLOYED_COMMIT when Commit arrives. See ingestion/idempotency.md. |
| **Anomaly before Git sync** | Block or quarantine Anomaly if File not found; retry when Git has synced. Or: queue Anomaly; process when Files exist. |
| **Commits out of chronological order** | Accept; Commits are immutable. Graph stores all; "last modified" uses timestamp ordering at query time. |
| **Anomalies out of chronological order** | Accept; each Anomaly is independent. Window completeness uses watermark, not ingest order. |
| **Deployments out of chronological order** | Accept; each Deployment is independent. Correlation uses timestamp at query time. |

### Not Tolerated (Block or Reject)

| Scenario | Behavior |
|----------|----------|
| **StackFrame without File** | Partial: degrade; create StackFrame without IN_FILE. Entire trace unresolved: block. |
| **Deployment DEPLOYED_COMMIT to non-existent Commit** | Block or pending; I3 requires DEPLOYED_COMMIT. Commit must exist before DEPLOYED_COMMIT. |
| **Anomaly without frames** | Block; I1 requires at least one HAS_FRAME. |

---

## 4. Watermark Strategy for Anomaly Windows

### Purpose

Decide when a time window is "complete" — no more anomalies expected — so RCA can run without missing late-arriving data.

### Watermark Definition

**Watermark** = the oldest event time we have not yet seen. Formally: a threshold T such that we assume all events with timestamp < T have been ingested.

**Practical:** `watermark = max(observed_timestamp) - allowed_lateness` or `watermark = current_wall_time - allowed_lateness`.

### Window Completeness

| Rule | Description |
|------|-------------|
| **Window complete** | For window [start, end), window is complete when watermark > end + allowed_lateness. |
| **RCA trigger** | Run RCA for a window only when the window is complete. |
| **Allowed lateness** | Configurable; e.g. 5–15 minutes for logs; 1 hour for batch pipelines. |

### Strategy Options

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **Fixed delay** | watermark = now - delay (e.g. 10 min). Windows with end < watermark are complete. | Streaming; low latency. |
| **Batch boundary** | watermark = max timestamp in batch. Next batch advances watermark. | Batch ingestion. |
| **Explicit watermark** | Source emits watermark events. | Event-driven; source-controlled. |

### MVP Recommendation

- **Batch:** watermark = max(Anomaly.timestamp) in batch. Run RCA for windows whose end < watermark - allowed_lateness.
- **Streaming:** watermark = now - allowed_lateness (e.g. 10 min). Run RCA for windows with end < watermark.

---

## 5. Clock Skew Handling

### Problem

Different sources (logs, Git, deployments) may use different clocks. Anomaly.timestamp and Deployment.timestamp might be skewed relative to each other.

### Impact

- **Deployment timing validation:** "Was commit deployed before incident?" compares Deployment.timestamp < Anomaly.timestamp. Skew can cause false positives or false negatives.
- **Commit ordering:** "Last commit to touch file" uses Commit.timestamp. Skew between Git author time and log time can misorder.

### Mitigations

| Mitigation | Description |
|------------|-------------|
| **UTC normalization** | All timestamps stored in UTC. Reduces timezone skew. |
| **Source sync** | Use NTP or equivalent on log servers, CI/CD, Git hosts. Minimize skew at source. |
| **Tolerance buffer** | For "deployed before incident": treat as valid if Deployment.timestamp < Anomaly.timestamp + skew_buffer (e.g. 60s). Document buffer. |
| **Confidence degradation** | When timestamps are close (within skew_buffer), lower confidence in deployment correlation signal. |
| **Audit** | Log source and timestamp for correlation decisions; enable post-hoc skew analysis. |

### MVP Recommendation

- Store all timestamps in UTC.
- Document max expected skew (e.g. 60s) and use as tolerance buffer for deployment correlation.
- Do not block on skew; degrade confidence when timestamps are within buffer.

---

## 6. Summary

| Aspect | Rule |
|--------|------|
| **Order** | Git → Logs → Deployments (by dependency). Git before Logs so Files exist. |
| **RCA readiness** | Anomaly + frames + IN_FILE; Git synced for repo scope; Deployments optional. |
| **Out of order** | Deployment before Commit → pending backfill. Anomaly before File → block or queue. |
| **Watermark** | Window complete when watermark > end + allowed_lateness. Run RCA only for complete windows. |
| **Clock skew** | UTC; tolerance buffer for deployment correlation; degrade confidence when close. |
