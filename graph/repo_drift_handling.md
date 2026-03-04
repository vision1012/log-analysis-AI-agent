# Repo Drift Handling — Graph Correctness Over Time

Minimal strategy for keeping the graph correct as repos change, without reprocessing everything.

**v1 constraint:** No new relationship types. Use node properties only. RENAMED_TO and REPLACES are v2.

**v1 property additions:** File gains `canonical_path`, `previous_paths`; Commit gains `replaces_sha`. All optional; backfill when drift is detected.

**File identity (locked):** `file_id = hash(repo_ref + "|" + canonical_repo_relative_path)`. Immutable. See `graph/ontology.md` and `ingestion/git_mining_spec.md`.

---

## Problem Summary

| Change Type | Effect on Graph | Risk |
|-------------|-----------------|------|
| File renames | File path stale; StackFrame→File and Commit→File may point to old path | Broken traversal; "last modified" wrong |
| Symbol moves | Symbol in new file; old attributions point to old file | Historical recurrence may miss; no broken links |
| Rebases/squashes | Commit SHAs change; Deployment points to old SHA | Deployment correlation fails; "last modified" stale |
| Deployments missing commits | Deployment has no DEPLOYED_COMMIT | I3 violated; timing validation impossible |

---

## 1. File Renames (v1: Properties Only)

### What Happens

A file moves from path A to path B. Commits in history touched A; current code lives at B. StackFrames may reference either.

### v1 Strategy: File Properties

| Property | Type | Purpose |
|----------|------|---------|
| file_id | string | Immutable identity. hash(repo_ref + "|" + canonical_path at creation). See ontology.md. |
| path | string | Identity path at creation (immutable). Same as input to file_id hash. |
| canonical_path | string | Current path after renames; "where it lives now" |
| previous_paths | array of string | Paths this logical file had before; chronological [oldest, …, newest before canonical] |

**Semantics:**
- On creation: `file_id` = hash(repo_ref + "|" + canonical(path)); `path` = identity path; `canonical_path` = path; `previous_paths` = [].
- On rename A→B detected: Update existing File(A): set `canonical_path` = B; set `previous_paths` = [A, …]. Do **not** create File(B). Do **not** change `file_id` or `path`.
- For "same logical file": One File node. Identity preserved via immutable file_id.

### Backfill (Delta Only)

- Run rename detection on repo (e.g. git log --follow, or diff-based).
- For each newly detected rename: resolve File by file_id = hash(repo_ref + "|" + canonical(old_path)); update with canonical_path=new_path and previous_paths=[old_path, …]. Do not create File(new_path).
- Do not reprocess all commits; only process renames not yet in graph.

### Query Behavior

- "Current path for this file": use `canonical_path`.
- "Last commit to touch this file": find File where canonical_path = X or path = X or X in previous_paths; traverse TOUCHED; take max timestamp.
- "StackFrame in file": Frame points to File by file_id; File identity is stable across renames.

### Invariant

`canonical_path` is the leaf. Chain of renames A→B→C: one File node (created at A) has file_id = hash(A), canonical_path=C, previous_paths=[A,B]. No File(B) or File(C) created.

### Graduation to v2 (RENAMED_TO)

When to add RENAMED_TO:
- Query volume for "same logical file" across renames is high and property-based lookup is slow.
- Multi-repo or cross-repo rename tracking is needed.
- Audit needs explicit relationship for "file X was renamed from Y".

**v2 migration:** Create RENAMED_TO from File(old_path) to File(new_path) for each entry in previous_paths; optionally deprecate previous_paths (keep canonical_path for convenience).

---

## 2. Refactors (Symbol Moves)

### What Happens

A function moves from file A to file B. Symbol name unchanged. Old attributions point to (symbol, file A); new traces point to (symbol, file B).

### Strategy

| Action | When | Effect |
|--------|------|--------|
| **No explicit move tracking** | — | Symbol+file is the identity; historical data stays as-is |
| **Query by symbol_name** | For "historical recurrence" | Match on symbol_name across files; file is secondary |

### Why No Backfill

- Old StackFrames correctly point to old File. Links are not broken.
- New StackFrames point to new File. No update to old data needed.
- "Same function" for recurrence = same symbol_name; file can differ across incidents.

### Edge Case

If file A was deleted and symbol only exists in B: File A may become orphan. Handle via orphan cleanup (I17, I18). No canonical_path update if file was deleted (not renamed).

---

## 3. Rebases and Squashes (v1: Properties Only)

### What Happens

Commit abc123 becomes def456 after rebase. Deployment points to abc123; current repo has def456. "git log" returns new SHAs.

### v1 Strategy: Commit Properties

| Property | Type | Purpose |
|----------|------|---------|
| sha | string | Commit SHA (immutable) |
| replaces_sha | string | New SHA after rebase/squash; set on old Commit when mapping known |

**Semantics:**
- Old Commit(abc123) keeps sha=abc123; Deployment→Commit stays correct.
- When mapping detected: create Commit(def456) if missing; set Commit(abc123).replaces_sha = def456.
- "Current SHA for this logical commit": if replaces_sha is set, use it; else use sha.

### Detection

- Same author, same timestamp (or close), same diff, same parent chain structure.
- Or: deployment/CI metadata that maps old SHA to new SHA.
- Or: manual backfill when operator provides mapping.

### Backfill (Delta Only)

- When syncing repo: get current commit list.
- For each Commit in graph with sha not in current repo: attempt to find matching new SHA (heuristics above).
- If match: create Commit(new_sha) if missing; set old Commit.replaces_sha = new_sha.
- Do not delete or modify old commits; deployment references stay valid.

### Query Behavior

- "What was deployed": use Deployment→Commit(old_sha); no change.
- "Last commit to touch file" (current branch): if Commit has replaces_sha, prefer that Commit for "current"; else use sha.
- "Commit exists in repo": check if sha in current refs; if not, check replaces_sha.

### Invariant

replaces_sha is at most one; acyclic (old points to new).

### Graduation to v2 (REPLACES)

When to add REPLACES relationship: query volume for rebase resolution is high; multi-hop rebase chains; explicit relationship needed for graph algorithms.

---

## 4. Deployments Missing Commit Lists

### What Happens

Deployment record exists (version X deployed at time T) but commit list is unknown. I3 requires DEPLOYED_COMMIT.

### Strategy

| Action | When | Effect |
|--------|------|--------|
| **Create Deployment with placeholder** | When deployment event received | Deployment node exists; no DEPLOYED_COMMIT |
| **Mark pending_backfill** | On creation without commit | Property: backfill_status = pending |
| **Add DEPLOYED_COMMIT when known** | When commit list arrives | Link to Commit(s); clear pending |

### Backfill (Delta Only)

- Periodic job: fetch commit list for deployments with backfill_status = pending.
- Sources: CI/CD API, release metadata, git tag annotation.
- For each resolved: create Commit if missing; add DEPLOYED_COMMIT; set backfill_status = complete.
- Do not reprocess deployments already complete.

### Invariant

Deployments with backfill_status = pending are excluded from Pre-RCA and timing validation until DEPLOYED_COMMIT exists.

---

## Summary: Backfill and Drift Handling

### Delta-Only Principle

Never reprocess the full repo. Only process:

| Change | What to Process | Frequency |
|--------|-----------------|-----------|
| File renames | New renames; update canonical_path, previous_paths | On repo sync or on-demand |
| Rebases | New Commit SHAs; set replaces_sha on old Commits | On repo sync |
| Deployments missing commits | Deployments with backfill_status = pending | Periodic (e.g. hourly) |
| Symbol moves | Nothing | — |

### Processing Order

1. Sync commits (new SHAs, replaces_sha).
2. Sync file renames (canonical_path, previous_paths).
3. Backfill deployment commits (DEPLOYED_COMMIT).
4. Orphan cleanup (optional; low priority).

### What Not to Do

| Avoid | Reason |
|-------|--------|
| Reprocess all commits | Expensive; unnecessary |
| Overwrite File.path | Breaks historical Commit→File links |
| Delete old commits | Breaks Deployment→Commit |
| Block RCA on pending deployments | Exclude from scope; run with available data |

### Graceful Degradation

When drift exists and cannot be resolved:

- **File rename unknown:** "Last modified" may miss commits to new path; report as best-effort.
- **Rebase mapping unknown:** Deployment correlation may fail for rebased commits; flag for manual mapping.
- **Deployment commits unknown:** Exclude deployment from timing validation; RCA proceeds without deployment signal.
