# `scripts/` — operational and smoke scripts

Runnable from repo root (often with `PYTHONPATH=.`).

| File | Purpose |
|------|---------|
| `seed_users.py` | Seeds sample `users` rows in Postgres via `POSTGRES_URL` |
| `smoke_test_rca_api.py` | Smoke test against RCA HTTP endpoints |
| `smoke_test_graph.py` | Smoke test Neo4j graph connectivity/writes |
| `smoke_test_graphrag.py` | Smoke test GraphRAG pipeline |
| `validate_e2e_ollama_flow.py` | End-to-end Ollama flow validation |
| `setup_and_test_api.sh` | Shell helper to bring up API and run checks |
