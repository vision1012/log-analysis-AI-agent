# Auto-Accept Policy — Future Planning

**Status:** Planning only. **NOT enabled in MVP.** This document defines a safe future upgrade path where RCA can auto-accept a root cause.

---

## 1. Scope and Prerequisites

### What Auto-Accept Means

When an RCA run produces a top-ranked candidate that satisfies all policy gates, the system may write RCA_ATTRIBUTED with status=accepted instead of candidate. Human confirmation is bypassed.

### MVP Behavior (Current)

| Rule | Behavior |
|------|----------|
| **All attributions** | status=candidate. No automatic acceptance. |
| **Human required** | Every attribution requires human confirm or reject. |

### Future (This Document)

| Rule | Behavior |
|------|----------|
| **When policy satisfied** | Optionally write status=accepted. Human can still rollback. |
| **When policy not satisfied** | status=candidate. Human required. |

---

## 2. Required Precision Threshold

### Gate

| Parameter | Required Value | Purpose |
|-----------|----------------|---------|
| **Precision@1** | > 95% | Before enabling auto-accept, the system must demonstrate that rank-1 attributions are correct at least 95% of the time (when human has confirmed). |

### Scope

| Scope | Rule |
|-------|------|
| **Per service_ref** | Precision@1 must exceed 95% for the service where auto-accept is enabled. |
| **Global** | Optionally require global Precision@1 > 95% as well. |
| **Rolling window** | Compute over last N days (e.g. 90 days) of human-confirmed attributions. |

### Enforcement

| When | Action |
|------|--------|
| Precision@1 ≥ 95% | Auto-accept policy may be enabled (subject to other gates). |
| Precision@1 < 95% | Auto-accept must remain disabled. |

---

## 3. Minimum Historical Sample Size

### Gate

| Parameter | Required Value | Purpose |
|-----------|----------------|---------|
| **Minimum sample size** | ≥ 100 (configurable) | Precision@1 must be computed over at least enough human-confirmed attributions to be statistically meaningful. |

### Scope

| Scope | Rule |
|-------|------|
| **Per service_ref** | At least N anomalies with accepted attributions for that service in the evaluation window. |
| **Default N** | 100. |

### Rationale

Small samples yield unstable precision estimates. 95% over 20 samples is not reliable. 95% over 100+ samples is more trustworthy.

---

## 4. Confidence Threshold Policy

### Gate

| Parameter | Required Value | Purpose |
|-----------|----------------|---------|
| **Confidence threshold** | ≥ 0.85 (configurable) | Only auto-accept when the top-ranked candidate's confidence score meets or exceeds this threshold. |

### Policy

| Rule | Description |
|------|-------------|
| **Threshold** | Default 0.85. Only candidates with confidence ≥ threshold are eligible for auto-accept. |
| **Per-service override** | Optional: higher threshold (e.g. 0.90) for critical services. |
| **Rank-1 only** | Auto-accept applies only to rank-1 candidate. Rank-2 and rank-3 remain candidate. |

### Rationale

High confidence indicates strong signal agreement. Low confidence indicates uncertainty; human review required.

---

## 5. Required Strong Signals

### Gate

| Signal | Required | Purpose |
|--------|----------|---------|
| **deploy_proximity** | > 0 | Last-touch commit was deployed before the incident. Deployment correlation is available. |
| **top_frame** | = 1 | Rank-1 candidate's representative frame is at the top of the stack (frame_order=0). |

### Policy

| Rule | Description |
|------|-------------|
| **Both required** | Auto-accept only when BOTH deploy_proximity > 0 AND top_frame = 1. |
| **Why deploy_proximity** | Deployment correlation provides strong temporal evidence. "Deploy X happened before incident; commit X touched this file." Reduces false positives from coincidental correlation. |
| **Why top_frame** | Top frame is the failure point. Attributing to a deeper frame is riskier. |

### When Signals Are Missing

| Condition | Action |
|------------|--------|
| deploy_proximity = 0 | No auto-accept. Deployment data missing or not correlated. |
| top_frame = 0 | No auto-accept. Rank-1 candidate is not at top of stack. |
| Either missing | No auto-accept. Fall back to candidate. |

---

## 6. Kill-Switch Design

### Purpose

Allow immediate disable of auto-accept without code change or deployment. Operational safety.

### Mechanisms

| Mechanism | Description |
|----------|-------------|
| **Feature flag** | Global or per-service flag: `auto_accept_enabled`. When false, all attributions remain candidate. |
| **Config override** | Runtime config (e.g. env var, config service): `RCA_AUTO_ACCEPT_ENABLED=false`. |
| **Precision circuit breaker** | If Precision@1 (rolling) drops below threshold (e.g. 90%), auto-disable auto-accept. Re-enable only after human review. |
| **Rate limit** | Optional: cap auto-accepts per service per day. Exceeding cap disables auto-accept for remainder of period. |

### Kill-Switch Behavior

| Action | Effect |
|--------|--------|
| **Disable** | All new attributions written as status=candidate. No auto-accept. |
| **Existing accepted** | Unchanged. Human can rollback via confirmation workflow. |
| **Re-enable** | Requires all gates to pass again. Manual or automated approval. |

### Audit

| Requirement | Rule |
|-------------|------|
| **Log kill-switch events** | When auto-accept is disabled (manual or circuit breaker), log: timestamp, reason, service_ref, trigger. |
| **Retention** | 90 days minimum. |

---

## 7. Policy Summary: All Gates

| Gate | Required | Purpose |
|------|----------|---------|
| Precision@1 | > 95% | Proven accuracy |
| Sample size | ≥ 100 | Statistical validity |
| Confidence | ≥ 0.85 | High confidence |
| deploy_proximity | > 0 | Deployment correlation |
| top_frame | = 1 | Top of stack |
| Kill-switch | Disabled when triggered | Operational safety |

**All gates must pass** for auto-accept to occur. Any failure → status=candidate.

---

## 8. Implementation Notes (Future)

| Aspect | Note |
|--------|------|
| **Evaluation pipeline** | Requires evaluation/rca_metrics.md metrics to be computed regularly. Precision@1 and sample size must be available. |
| **Signal availability** | deploy_proximity requires Deployment and DEPLOYED_COMMIT. Services without deployment data never auto-accept. |
| **Rollback** | Human can rollback accepted. feedback/confirmation_workflow.md applies. |
| **Per-service** | Policy can be enabled per service_ref. Some services may have auto-accept; others may not. |

---

## 9. MVP Alignment

| MVP | Future |
|-----|--------|
| **status=candidate only** | status=accepted when policy satisfied |
| **No auto-accept** | Auto-accept when all gates pass |
| **Human required** | Human optional when policy satisfied; rollback available |

**This document is planning only. Do not implement auto-accept in MVP.**
