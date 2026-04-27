# Log Analysis AI Agent - Architecture & Workflow

**Last Updated:** April 14, 2026  
**Project:** Graph-Based RCA Platform v2  
**Repository:** log-analysis-AI-agent (vision1012/main)

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [System Components](#system-components)
3. [Data Flow Workflows](#data-flow-workflows)
4. [RCA Execution Pipeline](#rca-execution-pipeline)
5. [API Layer Architecture](#api-layer-architecture)
6. [Database Schema](#database-schema)
7. [Deployment Architecture](#deployment-architecture)
8. [Concurrency & Safety](#concurrency--safety)
9. [Error Handling & Recovery](#error-handling--recovery)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER APPLICATIONS                                 │
│                    (Frontend, JIRA, External Systems)                       │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      │ HTTP/REST
                                      │
                ┌─────────────────────▼──────────────────────┐
                │         FastAPI Service Layer              │
                │  (api/main.py - Port 8000)                │
                │                                            │
                │  ├─ RCA Routes (/api/v1/rca/*)           │
                │  ├─ Feedback Routes (/api/v1/feedback/*) │
                │  ├─ Auth Routes (/api/v1/auth/*)         │
                │  ├─ JIRA Routes (/api/v1/jira/*)         │
                │  └─ Health Check (/health)               │
                └──────────────────┬───────────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
                ▼                  ▼                  ▼
        ┌─────────────────┐ ┌──────────────┐ ┌────────────────┐
        │  RCA Service    │ │Feedback      │ │Auth/Users      │
        │(rca_service.py) │ │Service       │ │Service         │
        │                 │ │(feedback_    │ │(auth_lifecycle)│
        │  - Orchestrates │ │ service.py)  │ │                │
        │  - Locking      │ │              │ │ - Verification │
        │  - Evidence Mgmt│ │ - Confirms   │ │ - Password Rst │
        │  - Status Track │ │ - Rejects    │ │ - User CRUD    │
        └────────┬────────┘ │ - Rollbacks  │ └────────┬───────┘
                 │          └──────┬───────┘          │
                 │                 │                  │
                 ▼                 ▼                  ▼
        ┌──────────────────────────────────────────────────┐
        │        Business Logic & Orchestration            │
        │                                                  │
        │  ┌────────────────────────────────────────────┐  │
        │  │  Pre-RCA Gate (gates/pre_rca_gate.py)     │  │
        │  │  - Checks accepted attributions           │  │
        │  │  - Validates idempotency                  │  │
        │  │  - Applies business rules                 │  │
        │  └────────────────────────────────────────────┘  │
        │                      │                           │
        │                      ▼                           │
        │  ┌────────────────────────────────────────────┐  │
        │  │  Deterministic RCA Engine                  │  │
        │  │  (rca_engine/deterministic_rca_runner.py) │  │
        │  │                                            │  │
        │  │  ├─ Candidate Generator                   │  │
        │  │  ├─ Signal Computation                    │  │
        │  │  ├─ Ranking Model                         │  │
        │  │  └─ Evidence Bundle Creation              │  │
        │  └────────┬─────────────────────────────────┘  │
        │           │                                     │
        │           ▼                                     │
        │  ┌────────────────────────────────────────────┐  │
        │  │  GraphRAG Layer (graphrag/)                │  │
        │  │  - LLM Explanation Generation              │  │
        │  │  - Context Packing                         │  │
        │  │  - Evidence Summarization                  │  │
        │  └────────────────────────────────────────────┘  │
        └──────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
    ┌──────────┐      ┌─────────┐       ┌────────────┐
    │Neo4j RCA │      │Evidence │       │PostgreSQL  │
    │Graph DB  │      │Store    │       │User DB     │
    │          │      │(File)   │       │            │
    │- Anomaly │      │         │       │- Users     │
    │- Files   │      │- Bundles│       │- Sessions  │
    │- Traces  │      │- Signals│       │- Feedback  │
    │- Commits │      │- Ranking│       │            │
    │- RCA Edges│     └─────────┘       └────────────┘
    └──────────┘
        │
        └──Network─────────────┐
                               │
                        ┌──────▼─────┐
                        │  Redis     │
                        │  (optional)│
                        │            │
                        │- Locking   │
                        │- Rate Limit│
                        │- Jobs Queue│
                        └────────────┘
```

---

## System Components

### **1. API Layer** (`api/`)
**Responsibility:** HTTP request routing, request validation, response formatting

**Key Files:**
- `main.py` - FastAPI app initialization, CORS, middleware setup
- `routers/rca_routes.py` - RCA execution endpoints
- `routers/feedback_routes.py` - User feedback endpoints
- `routers/auth_routes.py` - Authentication & user management
- `services/rca_service.py` - RCA orchestration logic
- `services/feedback_service.py` - Feedback processing logic
- `middleware/observability.py` - Request logging & tracing

**Endpoints:**
```
POST   /api/v1/rca/run/{anomaly_id}           # Trigger RCA
POST   /api/v1/rca/rerun/{anomaly_id}         # Rerun RCA (force)
GET    /api/v1/rca/results/{anomaly_id}       # Get RCA results
GET    /api/v1/rca/run-status/{anomaly_id}    # Check run status
GET    /api/v1/rca/result-view/{anomaly_id}   # Formatted results

POST   /api/v1/feedback/confirm/{anomaly_id}  # Accept attribution
POST   /api/v1/feedback/reject/{anomaly_id}   # Reject one
POST   /api/v1/feedback/reject-all/{anomaly_id} # Reject all
POST   /api/v1/feedback/rollback/{anomaly_id} # Undo feedback

GET    /health                                 # Health check
```

---

### **2. RCA Engine** (`rca_engine/`)
**Responsibility:** Core deterministic root-cause analysis logic (no LLM)

**Key Files:**
- `deterministic_rca_runner.py` - Main entry point
- `rca_runner.py` - Orchestration engine
- `candidate_generator.py` - Generates file candidates from traces
- `signal_computation.py` - Computes signals/metrics
- `ranking_model.py` - Ranks candidates deterministically

**Process:**
1. Fetch anomaly context from Neo4j
2. Extract stack traces → generate file candidates
3. Compute signals (frequency, depth, error patterns)
4. Rank candidates by weighted model
5. Create evidence bundles
6. Atomically write RCA_ATTRIBUTED edges

---

### **3. Quality Gates** (`gates/`)
**Responsibility:** Validate RCA execution conditions before/after ingestion

**Key Files:**
- `pre_rca_gate.py` - Pre-execution validation
  - Blocks if accepted attribution exists
  - Ensures idempotency (no duplicate run_ids)
  - Checks data quality invariants

- `post_ingestion_gate.py` - Post-ingestion validation
  - Validates event data shape
  - Enforces ordering constraints

---

### **4. Graph Layer** (`graph/`)
**Responsibility:** Neo4j connectivity and schema management

**Key Files:**
- `neo4j_client.py` - Driver wrapper (read/write operations)
- `writer.py` - Idempotent node/edge upserts
- `migrations.py` - Schema constraints & indexes

**Features:**
- Canonical path normalization
- File ID generation via SHA-256 hash
- Atomic transactions for batch writes
- Idempotent upserts (safe for retries)

---

### **5. GraphRAG Layer** (`graphrag/`)
**Responsibility:** LLM-assisted explanation generation

**Key Files:**
- `llm_client.py` - LLM provider invocation (OpenAI/Ollama)
- `prompt_builder.py` - Prompt construction from templates
- `context_packer.py` - Packs graph + evidence into bounded context
- `evidence_summarizer.py` - Summarizes evidence for prompts
- `explanation_generator.py` - Generates natural-language explanations

**Relation to RCA:** Supplements deterministic RCA; doesn't replace it

---

### **6. Artifacts Store** (`artifacts/`)
**Responsibility:** Evidence bundle persistence

**Key Files:**
- `evidence_store.py` - Abstract `EvidenceStore` protocol
- `LocalFileEvidenceStore` - File-backed implementation

**How it works:**
- Each bundle stored as `<uuid>.json` in configurable directory
- Contains: ranking, signals, trace data, file attributions
- Referenced by `evidence_ref` ID in RCA results

---

### **7. Database Layer** (`db/`)
**Responsibility:** Data persistence abstraction

**PostgreSQL** (`db/postgres/`)
- User identity & authentication
- Sessions, verification tokens, password resets
- Investigation metadata (if applicable)

**Neo4j** (`db/neo4j/`)
- RCA graph entities (Anomaly, File, StackFrame, Commit, Deployment)
- RCA_ATTRIBUTED edges (relationships between anomalies and files)
- Job execution records

---

### **8. Background Jobs** (`jobs/`)
**Responsibility:** Async task orchestration and concurrency control

**Key Files:**
- `rca_jobs.py` - Celery job entrypoints
- `job_locking.py` - Redis-based distributed locking

**Job Types:**
- Auto RCA (triggered by ingestion)
- Manual RCA (triggered by user)
- Rerun RCA (supersedes prior results)

---

### **9. Debug Agent Pipeline** (`debug_agent/`)
**Responsibility:** Multi-agent investigation orchestration

**7-Agent Pipeline:**
1. **Triage Agent** - Initial anomaly assessment
2. **Evidence Agent** - Gathers & structures evidence
3. **RCA Agent** - Bridges to deterministic RCA
4. **Memory Agent** - Context management
5. **Explanation Agent** - LLM-assisted explanation
6. **Remediation Agent** - Suggested fixes
7. **Reporting Agent** - Final structured report

**Key File:**
- `orchestrator.py` - Runs full pipeline; handles retries & aggregation

---

## Data Flow Workflows

### **Workflow 1: Manual RCA Trigger**

```
User → API /rca/run/{anomaly_id}
  │
  ├─→ Validate request (idempotency_key)
  │
  ├─→ RCA Service:
  │    ├─ Acquire lock on anomaly_id
  │    ├─ Run Pre-RCA Gate
  │    │   └─ Check: accepted attribution exists? → BLOCK
  │    │   └─ Check: idempotency (run_id duplicate?) → BLOCK
  │    │
  │    ├─ If gate PASS:
  │    │    ├─ Run Deterministic RCA
  │    │    │   ├─ Query Neo4j for anomaly context
  │    │    │   ├─ Generate candidates from stack frames
  │    │    │   ├─ Compute signals
  │    │    │   ├─ Rank candidates
  │    │    │   ├─ Create evidence bundle → Evidence Store
  │    │    │   └─ Atomically write RCA_ATTRIBUTED edges
  │    │    │
  │    │    ├─ Run GraphRAG (optional)
  │    │    │   ├─ Pack context (graph + evidence)
  │    │    │   ├─ Build prompt
  │    │    │   ├─ Invoke LLM
  │    │    │   └─ Generate explanation
  │    │    │
  │    │    └─ Return result: {status, run_id, bundle_ids, explanation}
  │    │
  │    └─ Release lock
  │
  └─→ Response: 200 OK {status: "success", ...} or 409 CONFLICT {code, message}
```

---

### **Workflow 2: User Feedback (Confirm/Reject)**

```
User → API /feedback/confirm/{anomaly_id}
  │
  ├─→ Validate feedback request
  │
  ├─→ Feedback Service:
  │    ├─ Acquire lock on anomaly_id
  │    │
  │    ├─ Load current RCA result from Neo4j
  │    │
  │    ├─ For CONFIRM:
  │    │    └─ Set RCA_ATTRIBUTED edge status → CONFIRMED
  │    │
  │    ├─ For REJECT:
  │    │    └─ Set RCA_ATTRIBUTED edge status → REJECTED
  │    │
  │    ├─ For REJECT-ALL:
  │    │    └─ Set all RCA_ATTRIBUTED edges status → REJECTED
  │    │
  │    ├─ For ROLLBACK:
  │    │    └─ Revert status, clear feedback
  │    │
  │    ├─ Update feedback timestamp in Neo4j
  │    │
  │    └─ Release lock
  │
  └─→ Response: 200 OK {status: "updated", ...}
```

---

### **Workflow 3: Rerun RCA (Force Supersede)**

```
User → API /rca/rerun/{anomaly_id}
  │
  ├─→ RCA Service (force=True):
  │    ├─ Acquire lock
  │    │
  │    ├─ Neo4j: Mark prior RCA_ATTRIBUTED edges → SUPERSEDED
  │    │
  │    ├─ Run new RCA (same as Workflow 1)
  │    │
  │    ├─ Atomically:
  │    │    ├─ Write new evidence bundle
  │    │    └─ Create new RCA_ATTRIBUTED edges (prior are SUPERSEDED)
  │    │
  │    └─ Release lock
  │
  └─→ Response: 200 OK {status: "success", run_id: "...", ...}
```

---

### **Workflow 4: Debug Agent Full Pipeline**

```
User → API /debug/run (anomaly_id, hint)
  │
  ├─→ Debug Agent Orchestrator:
  │    │
  │    ├─ TRIAGE AGENT
  │    │    ├─ Assess anomaly severity
  │    │    ├─ Initial categorization
  │    │    └─ Output: TriageReport
  │    │
  │    ├─ EVIDENCE AGENT
  │    │    ├─ Gather logs, metrics, events
  │    │    ├─ Structure evidence
  │    │    └─ Output: EvidenceBundle
  │    │
  │    ├─ RCA AGENT
  │    │    ├─ Call deterministic RCA
  │    │    ├─ Score candidates
  │    │    └─ Output: RCAResult
  │    │
  │    ├─ MEMORY AGENT
  │    │    ├─ Build context from prior steps
  │    │    ├─ Manage token budget
  │    │    └─ Output: ContextSummary
  │    │
  │    ├─ EXPLANATION AGENT
  │    │    ├─ LLM-based explanation
  │    │    ├─ Narrative generation
  │    │    └─ Output: Explanation
  │    │
  │    ├─ REMEDIATION AGENT
  │    │    ├─ Suggest fixes
  │    │    ├─ Estimate impact
  │    │    └─ Output: RemediationPlan
  │    │
  │    └─ REPORTING AGENT
  │         ├─ Aggregate outputs
  │         ├─ Format for UI/API
  │         └─ Output: InvestigationReport
  │
  └─→ Response: 200 OK {report: {...}, status: "success"}
```

---

## RCA Execution Pipeline

### **Deterministic RCA Step-by-Step**

```
Step 1: PRE-RCA GATE
├─ Check: accepted attribution exists? → YES → BLOCK (auto-run disabled)
├─ Check: same run_id already processed? → YES → BLOCK (idempotency)
├─ Check: deployment missing? → YES → DEGRADE (continue with warnings)
└─ Result: PASS / BLOCK / DEGRADE

Step 2: CANDIDATE GENERATION (if gate PASS)
├─ Query Neo4j for stack trace frames
├─ Extract file paths from frames
├─ Normalize paths (canonical form)
├─ Generate file_id via SHA-256
├─ Create File candidates
└─ Output: List of candidate files

Step 3: SIGNAL COMPUTATION
├─ Frequency: How often does this file appear in traces?
├─ Depth: Position in call stack (earlier = higher signal)
├─ Error patterns: Does file appear in error lines?
├─ Commit recency: When was file last modified?
├─ Deployment coverage: Affected deployments?
└─ Output: Signal scores per candidate

Step 4: RANKING MODEL
├─ Weight signals (configurable)
├─ Compute composite score: weighted_sum(frequency, depth, error, recency, deployment)
├─ Sort candidates by score (descending)
├─ Assign confidence levels (HIGH, MEDIUM, LOW)
└─ Output: Ranked list of candidates

Step 5: EVIDENCE BUNDLE CREATION
├─ Aggregate signals, ranking, trace data
├─ Include file metadata (path, repo, commit)
├─ Store in Evidence Store (file-backed)
├─ Generate evidence_ref (UUID)
└─ Output: evidence_ref

Step 6: ATOMIC WRITE
├─ Within transaction:
│  ├─ Supersede prior RCA_ATTRIBUTED edges (if rerun)
│  ├─ Create new RCA_ATTRIBUTED edges (anomaly → files)
│  ├─ Set edge properties: run_id, timestamp, evidence_ref, confidence
│  └─ Commit transaction
└─ Output: Edge creation success

Step 7: GRAPHRAG EXPLANATION (Optional)
├─ Pack context (anomaly, files, evidence)
├─ Build LLM prompt
├─ Invoke LLM (OpenAI/Ollama)
├─ Validate output
└─ Output: Explanation text

Step 8: RETURN RESULT
├─ anomaly_id, run_id, timestamp
├─ status: "success"
├─ candidates: [...ranked files...]
├─ evidence_bundles: [evidence_ref]
├─ explanation: "..."
└─ confidence: HIGH | MEDIUM | LOW
```

---

## API Layer Architecture

### **Request Flow**

```
HTTP Request
    │
    ├─→ Middleware Stack:
    │    ├─ CORS middleware (Allow-Origin)
    │    ├─ Rate limit middleware (Redis check)
    │    └─ Observability middleware (X-Request-Id, logging)
    │
    ├─→ FastAPI Router Matching
    │    └─ Route to appropriate handler
    │
    ├─→ Request Validation (Pydantic)
    │    ├─ Parse JSON body
    │    ├─ Type validation
    │    └─ Field validation (required, format, etc.)
    │
    ├─→ Dependency Injection
    │    ├─ Resolve dependencies (e.g., rate_limit check)
    │    └─ Inject into handler
    │
    ├─→ Business Logic Handler
    │    ├─ rca_service.trigger_manual_rca(...)
    │    ├─ feedback_service.confirm_feedback(...)
    │    └─ etc.
    │
    ├─→ Database Write (if applicable)
    │    ├─ Write to PostgreSQL (users, feedback)
    │    └─ Write to Neo4j (RCA edges, evidence)
    │
    ├─→ Response Formatting
    │    └─ Pydantic model to JSON
    │
    └─→ HTTP Response
         ├─ Status code (200, 409, 422, 500, etc.)
         └─ JSON body
```

### **Error Handling**

```
Exception Type          → Status Code → Response Format
─────────────────────────────────────────────────────
ValueError              → 422 (Unprocessable Entity)
HTTPException           → Specified status code
RCA gate blocked        → 409 (Conflict)
Transient DB error      → 503 (Service Unavailable)
Lock timeout            → 409 (Conflict)
Unhandled exception     → 500 (Internal Server Error)
```

---

## Database Schema

### **Neo4j Graph Model**

```
NODES:
├─ Anomaly
│  ├─ id (unique)
│  ├─ timestamp
│  ├─ trigger_type (e.g., "alert", "manual")
│  └─ metadata
│
├─ StackFrame
│  ├─ id (unique)
│  ├─ trace_ref
│  ├─ function_name
│  ├─ line_number
│  └─ file_path
│
├─ File
│  ├─ file_id (unique, SHA-256 hash)
│  ├─ path (canonical)
│  ├─ repo_ref
│  └─ language
│
├─ Commit
│  ├─ sha (unique with repo_ref)
│  ├─ repo_ref
│  ├─ timestamp
│  ├─ author
│  └─ message
│
└─ Deployment
   ├─ id (unique)
   ├─ timestamp
   ├─ version
   └─ metadata

EDGES:
├─ (Anomaly)-[:CONTAINS_TRACE]->(StackFrame)
├─ (StackFrame)-[:IN_FILE]->(File)
├─ (File)-[:LAST_MODIFIED_BY]->(Commit)
├─ (Deployment)-[:AFFECTS_FILE]->(File)
└─ (Anomaly)-[:RCA_ATTRIBUTED]->(File)
   ├─ run_id
   ├─ timestamp
   ├─ evidence_ref
   ├─ confidence (HIGH, MEDIUM, LOW)
   ├─ status (PENDING, CONFIRMED, REJECTED, SUPERSEDED)
   └─ feedback_timestamp (optional)
```

### **PostgreSQL Schema**

```
TABLE: users
├─ id (UUID, primary key)
├─ email (unique)
├─ password_hash
├─ verified (boolean)
├─ created_at
└─ updated_at

TABLE: verification_tokens
├─ id (UUID, primary key)
├─ user_id (foreign key)
├─ token_hash
├─ expires_at
└─ created_at

TABLE: password_resets
├─ id (UUID, primary key)
├─ user_id (foreign key)
├─ token_hash
├─ expires_at
└─ created_at

TABLE: feedback_logs (optional)
├─ id (UUID, primary key)
├─ anomaly_id
├─ user_id (foreign key)
├─ action (confirm, reject, rollback)
├─ timestamp
└─ notes
```

---

## Deployment Architecture

### **Development Setup**

```bash
# 1. Environment
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=dev_password
export POSTGRES_URL=postgresql://user:pass@localhost/rca_dev
export REDIS_URL=redis://localhost:6379/0
export GRAPHRAG_LLM_PROVIDER=ollama  # or openai

# 2. Migrations
python -m graph.migrations

# 3. API Server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### **Docker Compose Stack**

```yaml
services:
  api:
    image: python:3.11-slim
    ports: ["8000:8000"]
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - POSTGRES_URL=postgresql://postgres:password@postgres/rca
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - neo4j
      - postgres
      - redis

  neo4j:
    image: neo4j:5.x
    ports: ["7687:7687", "7474:7474"]
    environment:
      - NEO4J_AUTH=neo4j/dev_password

  postgres:
    image: postgres:15
    ports: ["5432:5432"]
    environment:
      - POSTGRES_DB=rca
      - POSTGRES_PASSWORD=password

  redis:
    image: redis:7
    ports: ["6379:6379"]

  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
```

### **Production Considerations**

```
├─ HTTPS only (TLS certificates)
├─ API rate limiting (via Redis)
├─ Request authentication (JWT tokens)
├─ Database replication & failover
├─ Evidence store on S3/GCS (not local filesystem)
├─ Metrics collection (Prometheus)
├─ Log aggregation (ELK/Datadog)
├─ Distributed tracing (Jaeger)
├─ Health checks & monitoring
└─ Auto-scaling (Kubernetes)
```

---

## Concurrency & Safety

### **Locking Strategy**

```
┌────────────────────────────────────────────┐
│  Distributed Lock (Redis-backed)           │
│                                            │
│  Key: `rca:lock:{anomaly_id}`             │
│  Value: `{lock_owner_uuid}`               │
│  TTL: 30 seconds (configurable)           │
│                                            │
│  ├─ Acquire: SET NX with TTL              │
│  ├─ Hold: Refresh before expiry           │
│  ├─ Release: DELETE after success/failure │
│  └─ Timeout: Fail if lock held > TTL      │
└────────────────────────────────────────────┘

Usage Pattern:
1. acquire_lock(anomaly_id, timeout_sec=30)
2. Execute RCA
3. release_lock(anomaly_id)  # or auto-release on timeout
```

### **Idempotency Guarantees**

```
Per-Anomaly per-Run:
├─ run_id uniqueness (pre_rca_gate check)
├─ Same run_id → same result (idempotent)
├─ Different run_id → new RCA execution

Evidence Bundle Deduplication:
├─ Same run → same evidence_ref
├─ Different run → different evidence_ref
└─ No duplicate processing

Atomic Writes:
├─ All-or-nothing transaction
├─ If edge write fails → entire RCA rolled back
├─ If evidence bundle fails → cleanup
└─ Consistent state guaranteed
```

---

## Error Handling & Recovery

### **Transient Errors**

```
Error Type                  → Action
────────────────────────────────────────
Neo4j connection timeout    → Retry (exponential backoff)
Redis connection error      → Fail-open (if configured)
LLM API timeout             → Skip GraphRAG (degraded mode)
Lock acquisition timeout    → Return 409 Conflict
Database constraint error   → Idempotent retry
```

### **Non-Transient Errors**

```
Error Type                  → Action
────────────────────────────────────────
Invalid request format      → Return 422 Validation Error
Missing required data       → Return 400 Bad Request
Unauthorized access         → Return 401/403
RCA gate blocked            → Return 409 Conflict + reason
Resource not found          → Return 404 Not Found
Unhandled exception         → Return 500 + log
```

### **Recovery Mechanisms**

```
1. Auto-Retry
   ├─ Transient errors: exponential backoff (1s, 2s, 4s, ...)
   ├─ Max retries: 3
   └─ Timeout: 60 seconds total

2. Graceful Degradation
   ├─ GraphRAG unavailable → return RCA without explanation
   ├─ Redis unavailable → disable rate limiting (fail-open)
   ├─ Evidence store unavailable → return partial results
   └─ LLM unavailable → skip explanation

3. Lock Cleanup
   ├─ Expired lock (TTL reached) → automatically released
   ├─ Process crash → lock TTL ensures cleanup
   └─ Manual unlock endpoint (admin only)

4. Rollback Mechanism
   ├─ User can rollback feedback via API
   ├─ Restores prior status
   └─ Triggers re-evaluation if needed
```

---

## Key Design Principles

### **1. Separation of Concerns**
- **RCA Engine:** Pure business logic (no HTTP, no DB directly)
- **API Layer:** HTTP routing & validation (no business logic)
- **Services:** Orchestration (bridges API ↔ RCA)
- **Graph:** Data persistence (no business rules)

### **2. Determinism**
- RCA scoring is rule-based, reproducible
- Same inputs → same ranking every time
- No randomization (except for tie-breaking)

### **3. Idempotency**
- Same request → same response (safe to retry)
- Distributed locking prevents duplicate execution
- Evidence bundles are immutable

### **4. Atomicity**
- RCA writes as single transaction
- Evidence bundle created before edge writes
- Rollback on any failure (no partial updates)

### **5. Auditability**
- All RCA runs logged with run_id
- Feedback tracked with user & timestamp
- Evidence bundles immutable (historical record)

### **6. Feedback-Driven**
- User can accept/reject/rollback
- Status transitions tracked
- Re-evaluation possible after feedback

---

## Monitoring & Observability

### **Metrics to Track**

```
RCA Performance:
├─ rca_execution_time (seconds)
├─ rca_candidates_generated
├─ rca_evidence_bundle_size (bytes)
└─ rca_attribution_confidence_distribution

System Health:
├─ api_request_count (per endpoint)
├─ api_request_latency (p50, p95, p99)
├─ api_error_rate (by status code)
├─ database_connection_pool_utilization

Lock Contention:
├─ lock_acquisition_time
├─ lock_timeout_count
├─ concurrent_rca_runs

GraphRAG:
├─ llm_invocation_count
├─ llm_latency
├─ llm_error_rate
└─ token_usage
```

### **Logging Strategy**

```
Levels:
├─ ERROR: Failures, exceptions, gate blocks
├─ WARN: Degraded mode, retries, timeouts
├─ INFO: RCA start/end, feedback actions, status changes
└─ DEBUG: Lock operations, signal computation, prompts

Fields:
├─ timestamp
├─ level
├─ module
├─ anomaly_id
├─ run_id
├─ user_id (if applicable)
├─ message
└─ stack_trace (for errors)
```

---

## Summary Table

| Component | Language | Purpose | Status |
|-----------|----------|---------|--------|
| `api/` | Python/FastAPI | HTTP REST service | **Active** |
| `rca_engine/` | Python | Deterministic RCA | **Active** |
| `gates/` | Python | Quality validation | **Active** |
| `graph/` | Python | Neo4j connectivity | **Active** |
| `graphrag/` | Python/LangChain | LLM explanations | **Active** |
| `artifacts/` | Python | Evidence storage | **Active** |
| `jobs/` | Python | Background tasks | **Active** |
| `db/` | Python | Data persistence | **Active** |
| `debug_agent/` | Python/LangChain | Multi-agent pipeline | **Active** |
| `tests/` | Python | Unit tests | **Maintained** |
| `scripts/` | Python/Shell | Smoke tests | **Utilities** |
| `old_log_arch_v1/` | Python | Legacy code | **Archived** |

---

## Getting Started

### **1. Local Development**

```bash
# Clone repo
git clone https://github.com/vision1012/log-analysis-AI-agent.git
cd log-analysis-AI-agent

# Copy environment template
cp env.example .env
# Edit .env with your credentials

# Install dependencies
pip install -r requirements.txt

# Run migrations
python -m graph.migrations

# Start API
uvicorn api.main:app --reload
```

### **2. Test RCA Workflow**

```bash
# In another terminal:
curl -X POST http://localhost:8000/api/v1/rca/run/anomaly-123 \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key": "req-001"}'

# Check results
curl http://localhost:8000/api/v1/rca/results/anomaly-123

# Confirm feedback
curl -X POST http://localhost:8000/api/v1/feedback/confirm/anomaly-123
```

### **3. Docker Compose**

```bash
# Start full stack
docker-compose up -d

# Wait for services to start (~30 seconds)
sleep 30

# Run smoke tests
python scripts/smoke_test_graph.py
python scripts/smoke_test_rca_api.py
```

---

**End of Architecture & Workflow Document**
