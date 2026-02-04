# RAG Design Proposal

**Status:** Design Document (No Code Changes)  
**Date:** 2026-02-04  
**Purpose:** Lock RAG implementation choices before coding

---

## Executive Summary

This document proposes a minimal RAG design that integrates with the existing job runtime architecture. The design prioritizes:
- **Job-scoped isolation**: All artifacts under `output/jobs/<job_id>/`
- **Schema compliance**: ToolResult validation via `validate_tool_result()`
- **Resume safety**: Idempotent indexing and retrieval
- **Future extensibility**: Abstract interfaces for vector stores and embedders

---

## 1. Chunking Strategy

### Current State
- `agent/rag/chunker.py` exists with:
  - `chunk_size=100` lines (default)
  - `overlap=10` lines (default)
  - Metadata extraction: timestamp, log_level, service

### Proposed Approach

**Chunking Parameters:**
```
- chunk_size: 100 lines (configurable, default 100)
- overlap: 10 lines (configurable, default 10)
- min_chunk_size: 20 lines (reject tiny chunks)
```

**Metadata Extraction:**
- **Timestamp**: Extract from log line patterns (ISO, dateutil parsing)
- **Log Level**: ERROR, WARN, INFO, DEBUG, FATAL, CRITICAL, TRACE
- **Service**: Extract from brackets `[ServiceName]` or prefix patterns
- **Chunk ID**: `chunk_{index}` (deterministic)

**Chunk Structure:**
```python
LogChunk(
    content: str,           # Raw log lines (joined)
    start_line: int,        # 1-indexed
    end_line: int,          # 1-indexed
    timestamp: datetime,     # Optional, from first line
    log_level: str,         # Optional, from first few lines
    service: str,           # Optional, from first few lines
    chunk_id: str           # "chunk_0", "chunk_1", etc.
)
```

**Rationale:**
- 100 lines balances context vs. granularity
- 10-line overlap prevents boundary issues
- Metadata enables filtering (by level, service, time)

---

## 2. Embeddings Choice

### Current State
- `agent/rag/embedder.py` supports:
  - `SentenceTransformerEmbedder` (local, `all-MiniLM-L6-v2`)
  - `OpenAIEmbedder` (API, `text-embedding-3-small`)

### Proposed Approach

**Default: Sentence-Transformers (Local)**
- **Model**: `all-MiniLM-L6-v2` (384 dimensions)
- **Why**: No API costs, works offline, fast for local dev
- **Provider**: `sentence-transformers` package

**Optional: OpenAI Embeddings**
- **Model**: `text-embedding-3-small` (1536 dimensions)
- **Why**: Better quality, but requires API key
- **Provider**: `openai` package
- **Fallback**: If API key missing, use sentence-transformers

**Embedding Interface:**
```python
class Embedder(ABC):
    def embed(texts: List[str]) -> List[List[float]]
    def embed_query(query: str) -> List[float]
```

**Configuration:**
- Environment variable: `RAG_EMBEDDER_PROVIDER` (default: `"sentence-transformers"`)
- Fallback logic: If OpenAI fails → use sentence-transformers

**Rationale:**
- Local-first for development/testing
- API option for production quality
- Graceful degradation

---

## 3. Vector Store Abstraction

### Current State
- `agent/rag/vector_store.py` has:
  - `ChromaVectorStore` (local, persistent)
  - Placeholder for Qdrant

### Proposed Approach

**Primary: Chroma (Local)**
- **Storage**: `output/vector_db/` (or `output/jobs/<job_id>/vector_db/` for job-scoped)
- **Persistence**: Chroma's built-in SQLite backend
- **Collection naming**: `log_chunks_<file_hash>` or `log_chunks_<job_id>`

**Future: Qdrant (Remote)**
- **Interface**: Same `VectorStore` ABC
- **Migration path**: Swap implementation, keep API

**Vector Store Interface:**
```python
class VectorStore(ABC):
    def add_chunks(chunks: List[Dict], embeddings: List[List[float]], collection_name: str)
    def search(query_embedding: List[float], top_k: int, collection_name: str, filter_dict: Dict) -> List[Dict]
    def delete_collection(collection_name: str)
```

**Abstraction Benefits:**
- Can switch Chroma → Qdrant without changing retriever code
- Test with in-memory mock
- Support multiple backends

---

## 4. Index Persistence Strategy

### Current State
- Vector DB location: `output/vector_db/` (global) or `output/jobs/<job_id>/vector_db/` (job-scoped)

### Proposed Approach

**Option A: Per-File Index (Recommended)**
- **Location**: `output/vector_db/<file_hash>/`
- **Collection name**: `log_chunks_<file_hash>`
- **File hash**: MD5 of file path + file size + last modified time
- **Benefits**: 
  - Reuse index across jobs for same file
  - Efficient: index once, query many times
  - Job-scoped queries still work

**Option B: Per-Job Index (Alternative)**
- **Location**: `output/jobs/<job_id>/vector_db/`
- **Collection name**: `log_chunks_<job_id>`
- **Benefits**:
  - Complete job isolation
  - Easy cleanup (delete job = delete index)
  - No cross-job contamination

**Recommendation: Hybrid (Per-File with Job Override)**
- **Default**: Per-file index (`output/vector_db/<file_hash>/`)
- **Job-scoped option**: If `JobOptions.rag_index_scope="job"`, use `output/jobs/<job_id>/vector_db/`
- **Rationale**: Best of both worlds

**Index Lifecycle:**
1. Check if index exists for file hash
2. If exists and file unchanged → reuse
3. If missing or file changed → rebuild
4. Store metadata: `index_metadata.json` with file hash, chunk count, created_at

---

## 5. Retrieval Results Storage

### Current State
- `agent/roles/retrieval_agent.py` saves to `output/jobs/<job_id>/retrieval.json`
- Worker adds artifact to `JobResult.artifacts`

### Proposed Approach

**File Structure:**
```
output/jobs/<job_id>/
├── retrieval.json              # Main retrieval results
├── retrieval_chunks/            # Optional: individual chunk files
│   ├── chunk_0.json
│   ├── chunk_1.json
│   └── ...
└── artifacts/                   # Tool artifacts (if any)
```

**retrieval.json Structure:**
```json
{
  "query": "why are timeouts happening",
  "chunks_indexed": 15,
  "chunks_retrieved": 5,
  "chunks": [
    {
      "chunk_id": "chunk_3",
      "content": "...",
      "metadata": {
        "start_line": 201,
        "end_line": 300,
        "timestamp": "2025-01-12T09:15:05",
        "log_level": "ERROR",
        "service": "DBService"
      },
      "distance": 0.23,
      "relevance_score": 0.77
    }
  ],
  "metadata": {
    "file_path": "output/jobs/.../inputs/sample.log",
    "top_k": 5,
    "embedder_provider": "sentence-transformers",
    "vector_store_provider": "chroma",
    "collection_name": "log_chunks_abc123"
  }
}
```

**Integration with Job Runtime:**
- Saved via `RetrievalAgent.save_retrieval_results()` → `output/jobs/<job_id>/retrieval.json`
- Added to `JobResult.artifacts` as `ArtifactRef`
- Resume check: If `retrieval.json` exists, skip retrieval agent

---

## 6. ToolResult Shape for run_retrieve_context

### Current State
- `utilities/retrieve_context.py` returns ToolResult via `create_tool_result()`
- Validated by `validate_tool_result()`

### Proposed ToolResult Shape

```json
{
  "tool": "run_retrieve_context",
  "status": "success",
  "input": {
    "file_path": "output/jobs/.../inputs/sample.log",
    "query": "why are timeouts happening",
    "top_k": 5,
    "keyword_filter": null,
    "log_level_filter": null
  },
  "summary": {
    "headline": "Retrieved 5 relevant chunks",
    "key_metrics": {
      "chunks_indexed": 15,
      "chunks_retrieved": 5,
      "query": "why are timeouts happening"
    }
  },
  "data": {
    "items": [
      {
        "chunk_id": "chunk_3",
        "content": "...",
        "metadata": {...},
        "relevance_score": 0.77
      }
    ],
    "text": "Retrieved 5 chunks for query: why are timeouts happening",
    "json": {
      "query": "why are timeouts happening",
      "top_k": 5,
      "chunks_indexed": 15,
      "chunks_retrieved": 5
    }
  },
  "artifacts": [
    {
      "type": "json",
      "name": "retrieval.json",
      "path": "output/jobs/.../retrieval.json"
    }
  ],
  "warnings": [],
  "errors": []
}
```

**Key Points:**
- `data.items`: List of retrieved chunks (full content + metadata)
- `data.json`: Summary statistics
- `artifacts`: Path to `retrieval.json` file
- `summary.headline`: Human-readable summary
- All fields validated by `ToolResult` Pydantic schema

---

## 7. Planner Decision: "Retrieve First"

### Current State
- `agent/planner/heuristic_planner.py` checks for keywords: `"why"`, `"what caused"`, `"analyze"`, `"understand"`, `"investigate"`
- `agent/planner/llm_planner.py` prompt mentions retrieval for context queries

### Proposed Approach

**Heuristic Planner Rules:**
```python
needs_retrieval = any(
    keyword in query_lower
    for keyword in [
        "why", "what caused", "what's causing",
        "analyze", "understand", "investigate",
        "root cause", "reason", "explain"
    ]
)

if needs_retrieval:
    tool_calls.append(
        ToolCall(
            name="run_retrieve_context",
            arguments={
                "file_path": file_path,
                "query": request.query,
                "top_k": 5
            }
        )
    )
```

**LLM Planner Prompt Addition:**
```
For queries that ask "why", "what caused", "analyze", or need context understanding:
1. FIRST call "run_retrieve_context" to retrieve relevant log chunks
2. THEN call analysis tools (run_log_summary, run_stacktrace, etc.)
```

**Decision Criteria:**
- **Question words**: "why", "what caused", "how did"
- **Analysis verbs**: "analyze", "investigate", "understand"
- **Context needs**: Queries requiring background/sequence understanding

**Tool Call Order:**
1. `run_retrieve_context` (if needed)
2. Analysis tools (`run_log_summary`, `run_stacktrace`, etc.)
3. Reporting tools (if any)

---

## Architecture Integration

### Job Runtime Flow

```
1. Worker creates job_dir: output/jobs/<job_id>/
2. Planner decides: needs retrieval? → add run_retrieve_context to plan
3. ToolExecutor executes run_retrieve_context:
   a. Check if retrieval.json exists → skip if found
   b. Check if index exists for file → reuse or build
   c. Retrieve top_k chunks
   d. Save to output/jobs/<job_id>/retrieval.json
   e. Return ToolResult (validated)
4. Investigation agent reads retrieval.json
5. Reporter agent uses findings + retrieval results
```

### Resume Behavior

- **Index reuse**: If file unchanged, reuse existing index
- **Retrieval reuse**: If `retrieval.json` exists, skip retrieval agent
- **Idempotent**: Multiple runs with same query → same results

---

## Design Checklist

### ✅ Chunking
- [x] Chunk size: 100 lines (configurable)
- [x] Overlap: 10 lines (configurable)
- [x] Metadata: timestamp, log_level, service
- [x] Chunk ID: deterministic (`chunk_{index}`)

### ✅ Embeddings
- [x] Default: sentence-transformers (local)
- [x] Optional: OpenAI (API)
- [x] Fallback: sentence-transformers if OpenAI fails
- [x] Interface: `Embedder` ABC

### ✅ Vector Store
- [x] Primary: Chroma (local, persistent)
- [x] Future: Qdrant (remote)
- [x] Interface: `VectorStore` ABC
- [x] Collection naming: `log_chunks_<file_hash>` or `log_chunks_<job_id>`

### ✅ Index Persistence
- [x] Strategy: Per-file index (default) with job-scoped option
- [x] Location: `output/vector_db/<file_hash>/` or `output/jobs/<job_id>/vector_db/`
- [x] Lifecycle: Check existence → reuse or rebuild
- [x] Metadata: Store file hash, chunk count, created_at

### ✅ Retrieval Results Storage
- [x] File: `output/jobs/<job_id>/retrieval.json`
- [x] Structure: query, chunks_indexed, chunks_retrieved, chunks array
- [x] Integration: Added to `JobResult.artifacts`
- [x] Resume: Check existence before retrieval

### ✅ ToolResult Shape
- [x] Schema: Compliant with `ToolResult` Pydantic model
- [x] Data: `items` (chunks), `json` (stats), `text` (summary)
- [x] Artifacts: Path to `retrieval.json`
- [x] Validation: Passes `validate_tool_result()`

### ✅ Planner Decision
- [x] Heuristic: Keyword matching for retrieval triggers
- [x] LLM: Prompt guidance for retrieval-first queries
- [x] Order: Retrieval → Analysis → Reporting
- [x] Criteria: Question words, analysis verbs, context needs

---

## Implementation Notes

### Dependencies
- `sentence-transformers>=2.2.0` (local embeddings)
- `chromadb>=0.4.0` (vector store)
- `openai>=1.0.0` (optional, for API embeddings)

### Configuration
- Environment variables:
  - `RAG_EMBEDDER_PROVIDER`: `"sentence-transformers"` or `"openai"`
  - `RAG_VECTOR_STORE_PROVIDER`: `"chroma"` or `"qdrant"`
  - `RAG_INDEX_SCOPE`: `"file"` (default) or `"job"`

### Error Handling
- Index build failure → return error ToolResult (don't crash)
- Retrieval failure → return error ToolResult (don't crash)
- Missing dependencies → graceful fallback or clear error message

### Testing
- Unit tests: Chunking, embedding, vector store operations
- Integration tests: End-to-end retrieval in job context
- Resume tests: Verify index reuse and retrieval skip

---

## Risks & Mitigations

### Risk 1: Index Size
- **Risk**: Large log files → large vector indices
- **Mitigation**: Per-file indexing, reuse across jobs, cleanup old indices

### Risk 2: Embedding Quality
- **Risk**: Local embeddings may miss semantic nuances
- **Mitigation**: Allow OpenAI fallback, document quality trade-offs

### Risk 3: Index Staleness
- **Risk**: File changes but index not updated
- **Mitigation**: File hash check (path + size + mtime), rebuild on mismatch

### Risk 4: Job Isolation
- **Risk**: Cross-job index contamination
- **Mitigation**: Job-scoped index option, collection naming with job_id

---

## Future Enhancements

1. **Hybrid Search**: Combine semantic (vector) + keyword (BM25)
2. **Reranking**: Use LLM to rerank top-K results
3. **Multi-file Indexing**: Index multiple files in one collection
4. **Incremental Indexing**: Update index when new logs arrive
5. **Index Compression**: Reduce storage for large indices

---

## Conclusion

This design integrates RAG into the existing job runtime with:
- ✅ Job-scoped artifact storage
- ✅ Schema-compliant ToolResult
- ✅ Resume-safe indexing
- ✅ Abstract interfaces for extensibility
- ✅ Clear planner decision logic

**Status**: Ready for implementation (design locked)
