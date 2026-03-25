# `scripts/` — operational and smoke scripts

Runnable from repo root (often with `PYTHONPATH=.`).

| File | Purpose |
|------|---------|
| `seed_users.py` | Seeds sample `users` rows in Postgres via `POSTGRES_URL` (idempotent skips). |
| `smoke_test_rca_api.py` | Smoke test against RCA HTTP endpoints. |
| `smoke_test_graph.py` | Smoke test Neo4j graph connectivity/writes. |
| `smoke_test_graphrag.py` | Smoke test GraphRAG pipeline pieces. |
| `smoke_test_debug_agent_wave1.py` | Wave 1 debug-agent integration smoke. |
| `smoke_test_debug_agent_wave2.py` | Wave 2 pipeline smoke. |
| `smoke_test_debug_agent_wave3.py` | Wave 3 (LangChain-assisted) pipeline smoke. |
| `setup_and_test_api.sh` | Shell helper to bring up API and run checks. |
