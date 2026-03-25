# `ingestion/` — ingestion specifications (design docs)

**No Python package here** — this folder holds **markdown specs** for how logs/events enter the system: contracts, ordering, idempotency, failure modes, deployment, stacktraces, git mining.

| File | Purpose |
|------|---------|
| `contracts.md` | Data contracts for ingested events. |
| `ordering.md` | Ordering guarantees across streams/batches. |
| `idempotency.md` | Idempotency keys and deduplication rules. |
| `failure_modes.md` | Expected failures and recovery behavior. |
| `deployment_spec.md` | How ingestion is deployed/operated. |
| `stacktrace_parsing_spec.md` | Rules for parsing stack traces from logs. |
| `git_mining_spec.md` | Spec for linking commits/diffs to incidents (if used). |

**Implementation** of ingestion may live in other services/repos; this directory is the **contract** for the platform.
