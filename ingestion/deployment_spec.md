# Deployment Ingestion Spec

How deployments are ingested: required fields, pending backfill, deterministic commit linking, and impact on RCA confidence.

---

## 1. Required Fields

### Must Have

| Field | Type | Constraint | Purpose |
|-------|------|------------|---------|
| deployment_id | string | Unique; max 64 chars | Deployment identity; dedupe key |
| service_ref | string | Max 64 chars | Service scope; matches Anomaly.service_ref for correlation |
| environment | string | Max 64 chars | e.g. prod, staging; scopes deployment |
| timestamp | string | ISO 8601 UTC | When deployment completed; for timing validation |
| commit_sha | string | 40 chars (SHA-1) or empty | Primary commit deployed; required for DEPLOYED_COMMIT when known |

### When commit_sha Is Empty

Deployment event exists but commit list is unknown (e.g. CI/CD emits deployment before artifact metadata). Create Deployment with backfill_status=pending; do not create DEPLOYED_COMMIT. See Pending Backfill below.

### Optional (Nice-to-Have)

| Field | Purpose |
|-------|---------|
| version_ref | Release/version identifier |
| repo_ref | Commit lookup scope (when multi-repo) |
| commit_shas | Array of commits (multi-commit deployment); see Linking below |

---

## 2. Pending Backfill

### Representation

| Property | Value | Meaning |
|----------|-------|---------|
| backfill_status | `pending` | Deployment created; commit list not yet known |
| backfill_status | `complete` | DEPLOYED_COMMIT exists; deployment is usable for correlation |

### When to Set pending

| Scenario | Action |
|----------|--------|
| Deployment event received, no commit_sha | Create Deployment; set backfill_status=pending; no DEPLOYED_COMMIT |
| Deployment event received, commit_sha present but Commit not in graph | Create Deployment; set backfill_status=pending; no DEPLOYED_COMMIT (Commit will arrive from Git) |
| Deployment event received, commit_sha present, Commit exists | Create Deployment; create DEPLOYED_COMMIT; set backfill_status=complete |

### Backfill Completion

| Trigger | Action |
|---------|--------|
| Commit list arrives (CI/CD API, release metadata) | Lookup Deployment by deployment_id; resolve Commits; create DEPLOYED_COMMIT; set backfill_status=complete |
| Git sync adds missing Commit | Backfill job retries; if Commit now exists, create DEPLOYED_COMMIT; set backfill_status=complete |

### Exclusion from RCA

Deployments with backfill_status=pending are excluded from:
- Pre-RCA gate (I3 check)
- Deployment timing validation
- Deploy proximity and deploy recency rank signals

RCA proceeds without deployment correlation for those deployments.

---

## 3. Linking Deployments to Commits Deterministically

### Single Commit (MVP)

| Rule | Description |
|------|-------------|
| **Resolve** | Lookup Commit by (repo_ref, commit_sha). repo_ref from deployment or service mapping. |
| **Create DEPLOYED_COMMIT** | Deployment -[:DEPLOYED_COMMIT]-> Commit. One edge per Deployment (I3). |
| **Validation** | Commit must exist. Commit.repo_ref must match service scope. |

### Deterministic Resolution

| Step | Rule |
|------|------|
| 1. **Scope** | service_ref maps to repo_ref (e.g. config or convention: service "api" → repo "org/api"). |
| 2. **Lookup** | Commit WHERE sha = commit_sha AND repo_ref = repo_ref. |
| 3. **Create** | If found: create DEPLOYED_COMMIT. If not found: backfill_status=pending. |
| 4. **Idempotency** | Same deployment_id + commit_sha → same DEPLOYED_COMMIT. Skip if exists. |

### Multiple Commits (Future)

When a deployment includes commits from multiple repos or multiple commits:

| Option | Description |
|--------|-------------|
| **Primary only** | Use one "primary" commit (e.g. first, or by convention). One DEPLOYED_COMMIT. MVP. |
| **Multiple DEPLOYED_COMMIT** | One Deployment, multiple DEPLOYED_COMMIT edges. Requires I3 relaxation (one-to-many). |
| **One Deployment per repo** | Split by repo; one Deployment per repo with its commit. |

**MVP:** One commit per deployment; primary commit only.

### commit_sha Format

| Source | Format | Handling |
|--------|--------|----------|
| Git SHA-1 | 40 hex chars | Use as-is |
| Short SHA | 7+ chars | Expand to full or match prefix; document matching rule |
| Tag | refs/tags/v1.0 | Resolve to commit SHA via git; store SHA in graph |

---

## 4. How Missing Commit Lists Affect RCA Confidence

### Deployment-Dependent Signals

From graph-derived signals for confidence scoring:

| Signal | Depends On | When Missing |
|--------|------------|--------------|
| **Deploy proximity** | Deployment.timestamp, DEPLOYED_COMMIT→Commit | Signal = 0; no deployment to compare |
| **Deploy recency rank** | Deployment is latest before incident | Signal = 0; cannot rank |
| **Deployment timing validation** | "Was commit deployed before incident?" | Cannot answer; exclude from validation |

### Confidence Impact

| Scenario | Impact |
|----------|--------|
| **All deployments have DEPLOYED_COMMIT** | Full deployment correlation; deploy signals contribute to confidence. |
| **Some deployments pending** | Exclude pending from correlation. Fewer deployments in scope; deploy signals may be 0 or based on partial data. |
| **All deployments pending** | No deployment correlation. Deploy proximity and deploy recency rank = 0. Overall confidence lower; RCA relies on other signals (top-frame, last-touch recency, historical recurrence). |
| **Commit not in graph (rebased/squashed)** | DEPLOYED_COMMIT may point to old SHA; replaces_sha not set. Deployment correlation may fail or be stale. Degrade confidence for that deployment. |

### Confidence Degradation Rules

| Condition | Action |
|-----------|--------|
| No deployments in scope | Deploy signals = 0; do not penalize other signals. |
| All deployments pending | Deploy signals = 0; document "deployment data unavailable" in evidence. |
| Partial deployments (some pending) | Use available deployments; lower weight for deploy signals when coverage is partial. |
| Commit not found (rebase/squash) | Exclude deployment; or include with confidence penalty. |

### Evidence Bundle

When deployment correlation is used: include deployment_id in evidence bundle. When missing: evidence bundle has no deployment_id; deployment_id optional. RCA can still produce attribution; confidence reflects absence of deployment signal.

---

## 5. Summary

| Aspect | Rule |
|--------|------|
| **Required fields** | deployment_id, service_ref, environment, timestamp; commit_sha when known |
| **Pending backfill** | backfill_status=pending; no DEPLOYED_COMMIT; excluded from RCA correlation |
| **Linking** | Resolve Commit by (repo_ref, commit_sha); create DEPLOYED_COMMIT; one per Deployment (MVP) |
| **Missing commits** | Deploy signals = 0; confidence lower; RCA proceeds with other signals |
