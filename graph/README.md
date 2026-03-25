# `graph/` — Neo4j graph I/O (RCA-oriented)

Neo4j connectivity and write paths used by RCA and related pipelines (distinct from `db/neo4j`, which targets **Job** nodes for the jobs API).

| File | Purpose |
|------|---------|
| `neo4j_client.py` | Thin wrapper: `GraphDatabase` driver, `execute_read` / `execute_write`, `from_env()`, health check. |
| `writer.py` | `GraphWriter` — writes nodes/edges for RCA artifacts into Neo4j. |
| `migrations.py` | Schema/index/constraint helpers or migration runners for the RCA graph model. |
| `__init__.py` | Package marker. |

**Note:** `graph/neo4j_client.py` is the **RCA-era** client; `db/neo4j/connection.py` is the **shared driver** for job persistence. Both talk to Neo4j; responsibilities differ.
