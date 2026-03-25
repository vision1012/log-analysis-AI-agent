# `gates/` — quality gates (pipeline invariants)

Pre/post checks around ingestion and RCA so only valid graph/evidence enters the deterministic core.

| File | Purpose |
|------|---------|
| `pre_rca_gate.py` | Validates inputs/state **before** deterministic RCA runs (structure, required fields, policy). |
| `post_ingestion_gate.py` | Validates graph/evidence **after** ingestion steps (consistency, completeness). |
| `__init__.py` | Package marker. |

**Role:** Keeps **deterministic RCA** trustworthy by rejecting bad upstream data early.
