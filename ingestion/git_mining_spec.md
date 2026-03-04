# Git Mining Spec — Deterministic Rules

Deterministic rules for mapping commits to files, handling renames, squashes, monorepo/multi-repo, merge commits, and bootstrap vs incremental mining.

Aligns with `graph/ontology.md` File Identity (locked).

---

## 1. File Identity (Locked)

### Formula

```
file_id = hash(repo_ref + "|" + canonical_repo_relative_path)
```

The path is the **identity path** — the path at first creation, normalized. Immutable.

### Hash

| Aspect | Rule |
|--------|------|
| Algorithm | SHA-256 |
| Output | 32 hex chars (first 16 bytes, lowercase) |
| Encoding | UTF-8 |

### Canonical Path Normalization

Apply before hashing and for all path comparisons:

| Rule | Description |
|------|-------------|
| Repo-relative | Strip leading `./`, `/`, or repo root prefix. |
| Separator | Forward slash `/` only. |
| Collapse | `//` → `/`. |
| Trailing slash | Strip. |
| Whitespace | Trim. |
| Unicode | NFC normalization. |

### Immutability

- **file_id never changes.** Once assigned at creation, immutable.
- On rename: update `canonical_path`, `previous_paths`; do **not** change `file_id` or create a new File.

### Renames (Identity Preservation)

When git reports rename A → B:

| Action | Rule |
|--------|------|
| **Update existing File** | File(A) exists. Set `canonical_path = B`, `previous_paths = [A, …]`. |
| **Do not create File(B)** | Same logical file; one File node. file_id stays hash(repo_ref + "|" + A). |
| **TOUCHED** | Commit -[:TOUCHED]-> File(A). File is identified by file_id; path used at commit time was A. |

---

## 2. Required Fields from Commit

### Must Have

| Field | Type | Source | Purpose |
|-------|------|--------|---------|
| sha | string | 40 chars (SHA-1) | Commit identity; unique per repo |
| timestamp | string | ISO 8601 UTC | Event time; for "last modified" ordering |
| repo_ref | string | Repo identifier | Scope; links Commit and File to repo |
| modified_files | array | List of paths | Populates TOUCHED edges |

### modified_files Entry

| Field | Required | Purpose |
|-------|----------|---------|
| path | Yes | Repo-relative path; used for File lookup/creation and TOUCHED |
| change_type | No | added, modified, deleted (v1: not used for TOUCHED) |

### Optional (Nice-to-Have)

| Field | Purpose |
|-------|---------|
| author | Audit; future filtering |
| message | Audit; future heuristics |
| parent_shas | Merge detection; graph structure |

---

## 3. Populating TOUCHED Edges

### Rule

For each commit and each path in modified_files: create or ensure Commit -[:TOUCHED]-> File.

### Steps

1. **Resolve File:** Normalize path; compute file_id = hash(repo_ref + "|" + canonical_path). Lookup File by file_id. Create if missing (path = identity path, file_id, canonical_path = path, previous_paths = []).
2. **Create TOUCHED:** Create edge from Commit to File. Dedupe by (commit_id, file_id); skip if exists.
3. **Path normalization:** Apply canonical path rules (§1) before lookup/creation.

### What Counts as "Touched"

| Change Type | Include in TOUCHED |
|-------------|-------------------|
| added | Yes |
| modified | Yes |
| deleted | Yes (file was touched; "last modified" includes deletion) |
| renamed | Yes for old path (File identity preserved; update canonical_path on existing File) |

### Rename Handling

When git reports a rename (old_path → new_path):

| Action | Rule |
|--------|------|
| **Resolve File** | Lookup by file_id = hash(repo_ref + "|" + canonical(old_path)). File exists from prior TOUCHED or create now. |
| **Update File** | Set canonical_path = new_path, previous_paths = [old_path, …]. Do not create File(new_path). |
| **Create TOUCHED** | Commit -[:TOUCHED]-> File (the single File node; file_id unchanged). |

### Idempotency

- Same (repo_ref, sha) + same modified_files → same TOUCHED edges. Skip if edges exist.
- See ingestion/idempotency.md.

---

## 4. Merge Commits

### Definition

Commit with more than one parent (git merge).

### Ingestion Rules

| Merge Type | TOUCHED | Commit Node |
|------------|---------|-------------|
| **Merge with diff** | Create TOUCHED for files actually changed (conflict resolution, etc.) | Create |
| **Merge without diff** | Do not create TOUCHED | Create (for deployment correlation) or skip |

**Rule:** Ignore merges without diffs for TOUCHED. Do not create TOUCHED edges for merge commits that have zero file changes (fast-forward, no conflicts). Create Commit node for deployment correlation if needed; modified_files = [].

### Last-Touch Logic

"Last touch" = the most recent commit that actually modified a file. Used for RCA ("which commit last modified that function's file").

| Rule | Description |
|------|-------------|
| **Only commits with TOUCHED** | Last-touch query considers only commits that have TOUCHED to the file. By definition, merges without diffs have no TOUCHED and are excluded. |
| **Actual file changes** | TOUCHED is created only when the commit's diff includes the file. Merges without diffs → no TOUCHED → excluded from last-touch. |
| **Merge with diff** | Merge that resolved conflicts and changed files has TOUCHED. Include in last-touch (it did modify the file). |
| **Optional: exclude all merges** | For "first-parent" lineage: when computing last-touch, optionally filter out merge commits (parent_count > 1) to prefer the non-merge commit that authored the change. Configurable. |

### Summary

- **Ingest:** Merges without diffs → no TOUCHED. Merges with diffs → TOUCHED for changed files.
- **Last-touch:** Uses only commits with TOUCHED to the file; naturally excludes merges without diffs. Optionally exclude all merges for first-parent lineage.

---

## 5. Renames (Detail)

### Detection

- Use `git log --follow` or diff with rename detection (e.g. `-M`).
- Git reports rename as: old_path (deleted) + new_path (added) with similarity.

### Rules

| Scenario | Action |
|----------|--------|
| **Rename A→B in commit** | Resolve File by file_id = hash(repo_ref + "|" + canonical(A)). Create if missing. TOUCHED to that File. Update File: canonical_path = B, previous_paths = [A]. |
| **Copy (A exists, B added)** | Not a rename. Create File(B) with file_id = hash(repo_ref + "|" + canonical(B)). TOUCHED to File(B) only. |
| **Delete only** | TOUCHED to File(A). File may become orphan if no IN_FILE; handle per I18. |

### Path at Commit Time

TOUCHED links Commit to File by file_id. File identity (file_id) is immutable. canonical_path and previous_paths track current location for query; they do not affect file_id.

---

## 6. Squashes and Rebases

### Squash

Multiple commits become one. New SHA; old SHAs may not exist in current branch.

**Rule:** Mine current branch as-is. Create Commit for each SHA in history. If deployment references old SHA (pre-squash), that Commit may not be in current branch. Handle via repo_drift_handling: Commit.replaces_sha when mapping is known. Do not try to infer squash during mining; that is a separate backfill step.

### Rebase

Commits get new SHAs. Old SHAs referenced by deployments.

**Rule:** Mine current branch. Create Commits for current SHAs. Old Commits (from deployment) may exist in graph from prior sync; they stay. Set replaces_sha when rebase mapping is detected (separate drift job).

### Mining Order

Mine in chronological order (oldest first) or reverse (newest first). Idempotent either way; TOUCHED and Commits dedupe. Chronological (oldest first) ensures parents exist when processing; optional for flat structure.

---

## 7. Monorepo / Multi-Repo

### Monorepo

Single repo with multiple services/components (e.g. `services/auth/`, `services/api/`).

| Aspect | Rule |
|--------|------|
| **repo_ref** | One repo_ref for entire repo. |
| **Path scope** | Optional: filter modified_files by path prefix (e.g. only `services/auth/**`) to limit scope. |
| **File path** | Full repo-relative path (e.g. `services/auth/src/handler.py`). |
| **service_ref** | Not on Commit/File; use path prefix or separate mapping for "which service" if needed. |

### Multi-Repo

Multiple repos; each mined independently.

| Aspect | Rule |
|--------|------|
| **repo_ref** | Unique per repo (e.g. `org/repo-a`, `org/repo-b`). |
| **Mining** | Run mining per repo. Commits and Files are scoped by repo_ref. |
| **Cross-repo** | No TOUCHED across repos. Deployment may deploy from multiple repos; Deployment→Commit links per repo. |
| **StackFrame** | StackFrame references File with repo_ref; frame path must resolve within that repo. |

### Cross-Repo Deployment

When a deployment includes commits from multiple repos: create one Deployment node; create DEPLOYED_COMMIT to each Commit (one edge per repo's commit). Or: one Deployment per repo. Document chosen model. MVP: one Deployment, one DEPLOYED_COMMIT to "primary" commit; or one Deployment per repo.

---

## 8. Bootstrap vs Incremental Mining

### Bootstrap (Initial Load)

| Aspect | Rule |
|--------|------|
| **Scope** | Full history or bounded by depth/date. |
| **Depth** | Configurable: `--max-depth N` (N commits from HEAD) or `--since date` (commits after date). |
| **Default** | Recommend: `--since 90 days` or `--max-depth 10000` for first run. Balance coverage vs cost. |
| **Branches** | Mine default branch (main/master) or specified ref. Multiple branches: each commit mined once (sha unique per repo). |
| **Order** | Chronological (oldest first) recommended for stable watermark; reverse also valid. |

### Incremental (Ongoing)

| Aspect | Rule |
|--------|------|
| **Trigger** | On schedule (e.g. hourly) or on webhook. |
| **Scope** | New commits since last mined SHA (or since last run timestamp). |
| **Range** | `git log last_mined_sha..HEAD` or `git log --since last_run_time`. |
| **Dedupe** | All commits dedupe by (repo_ref, sha). Idempotent. |
| **Missed commits** | If gap (e.g. force-push): re-mine from last known good; or full re-sync if gap too large. |

### Last Mined State

| Storage | Purpose |
|---------|---------|
| last_mined_sha | Per repo; SHA of most recent commit mined. Next run: log from this to HEAD. |
| last_mined_timestamp | Alternative; use for `--since` if wall-clock is preferred. |

### Watermark

Git mining does not use event-time watermark for completeness (unlike anomaly windows). Commits are immutable; incremental adds new commits. No "window complete" concept for Git.

---

## 9. Summary

| Aspect | Rule |
|--------|------|
| **File identity** | file_id = hash(repo_ref + "|" + canonical_path); SHA-256 truncated 32 hex; UTF-8; immutable |
| **Required fields** | sha, timestamp, repo_ref, modified_files (path) |
| **TOUCHED** | One per (Commit, File) for each path in modified_files; dedupe by (commit_id, file_id) |
| **Renames** | Update canonical_path, previous_paths on existing File; do not create new File; file_id unchanged |
| **Merge commits** | Include; TOUCHED only for merges with diffs; no TOUCHED for no-op merges; last-touch uses commits with actual file changes |
| **Squashes/rebases** | Mine current branch; replaces_sha in separate drift job |
| **Monorepo** | One repo_ref; full paths; optional path filter |
| **Multi-repo** | One repo_ref per repo; mine independently |
| **Bootstrap** | Full or bounded (e.g. 90 days, 10k commits) |
| **Incremental** | New commits since last_mined_sha; idempotent |
