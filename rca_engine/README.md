# `rca_engine/` — deterministic RCA (source of truth)

**Rule-based** root-cause analysis: signals, candidates, ranking — **no LLM** inside this package.

| File | Purpose |
|------|---------|
| `deterministic_rca_runner.py` | Facade: `run_deterministic_rca(...)` delegates to `rca_runner` with graph client, writer, evidence store wired in. |
| `rca_runner.py` | Core orchestration of a deterministic RCA run; produces `RCARunResult`. |
| `candidate_generator.py` | Builds candidate root-cause hypotheses from graph signals. |
| `signal_computation.py` | Computes signals/metrics from graph and logs. |
| `ranking_model.py` | Ranks/orders candidates by policy (deterministic). |
| `__init__.py` | Public exports. |

**Boundary:** API/services call into here; **GraphRAG** runs **after** or beside this, not instead of it.
