# Development Setup

Minimal guide for running Neo4j locally and required environment variables.

---

## Neo4j with Docker

### Start Neo4j

```bash
docker run -d \
  --name neo4j-rca \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your-password \
  neo4j:5
```

- **7474**: HTTP (browser UI)
- **7687**: Bolt (driver connection)

### Stop and Remove

```bash
docker stop neo4j-rca
docker rm neo4j-rca
```

### Run Migrations

```bash
# After setting NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
python -m graph.migrations
```

---

## Required Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | — | Bolt URI, e.g. `bolt://localhost:7687` |
| `NEO4J_USER` | Yes | — | Neo4j username (e.g. `neo4j`) |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |

### Example `.env`

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

---

## Optional: Artifact Store

For evidence bundle persistence (future):

| Variable | Description |
|----------|-------------|
| `EVIDENCE_STORE_URI` | Artifact store endpoint (S3, local path, etc.) |
| `EVIDENCE_STORE_BUCKET` | Bucket or prefix for bundles |

---

## Dependencies

For graph migrations and RCA:

```bash
pip install -r requirements.txt
```

## Verify JIRA-first RCA locally

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
python scripts/smoke_test_graph.py
python scripts/smoke_test_graphrag.py
# With API running:
python scripts/smoke_test_rca_api.py
```

