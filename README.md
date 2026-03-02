# 🚀 Log Analysis AI Agent  

An intelligent, end-to-end **AI-powered log analysis system** designed to streamline debugging, accelerate incident response, and extract actionable insights from complex logs.

---

## 👨‍💻 Genz Developers  
- **Jay Paun**  
- **Preet Patel**

---

## 🏗️ Project Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                        │
│         (CLI / REST API / Future: Desktop App, Mobile App)                       │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER (FastAPI)                                 │
│  POST /api/v1/jobs  │  GET /jobs/{id}  │  GET /report  │  GET /artifacts         │
│  Middleware: CORS, Observability (X-Request-Id, logging)                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           AGENT / PIPELINE LAYER                                 │
│  Job Store  │  Runner (background)  │  Worker (orchestrator)                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
┌──────────────────────────────┐         ┌──────────────────────────────────────┐
│   HEURISTIC MODE             │         │   RAG / LLM MODE                      │
│   Heuristic Planner          │         │   Retrieval → Investigation → Reporter │
│   (keyword → tool mapping)   │         │   Vector store, chunker, embedder      │
└──────────────────────────────┘         └──────────────────────────────────────┘
                    │                                       │
                    └───────────────────┬───────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TOOL EXECUTOR + TOOL REGISTRY                            │
│  time_slice │ search_keyword │ filter_log_level │ log_summary │ stacktrace       │
│  error_code │ error_lines │ retrieve_context                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         UTILITIES LAYER (run_* functions)                        │
│  Core log processing: slice_by_time, filter_by_log_level, extract_stacktraces   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MACHINE LEARNING LAYER (optional)                         │
│  HDFS parsing │ Template extraction │ IsolationForest │ Anomaly inference        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## ✅ Implemented Components

### 1. API Layer
- **FastAPI** app with CORS, observability middleware
- **Jobs router**: `POST /api/v1/jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/report`, `GET /jobs/{id}/artifacts`
- **Health router**: `/health`
- **Job store** (in-memory) and **runner** (background execution)
- **Schemas**: JobRequest, JobResponse, artifact metadata

### 2. Agent Layer
- **Worker** (`agent/runtime/worker.py`): Orchestrates job execution, resume support, idempotency
- **Planner router**: Heuristic or LLM mode
- **Heuristic planner**: Keyword-based tool selection (timeout, error, stacktrace, etc.)
- **LLM planner**: LLM-based tool selection (Ollama/LLaMA client)
- **Tool registry** + **tool executor**: Maps tool names to `run_*()` functions, validates results
- **RAG pipeline**:
  - **Retrieval agent**: Chunk logs → embed → vector store → retrieve context
  - **Investigation agent**: LLM analysis of retrieved context
  - **Reporter agent**: Generate markdown report
- **Storage**: Job directories (`runs/<job_id>/`), artifact paths, plan persistence

### 3. Utilities (Log Tools)
| Tool | Description |
|------|-------------|
| `run_time_slice` | Filter logs by time range |
| `run_search_keyword` | Search by keyword(s) |
| `run_filter_log_level` | Filter by ERROR, WARN, INFO, etc. |
| `run_log_summary` | AI-driven log summary |
| `run_stacktrace` | Extract and analyze stack traces |
| `run_error_code_search` | Search by error code(s) |
| `run_error_lines` | Extract error lines |
| `retrieve_context` | RAG retrieval from indexed logs |

### 4. Machine Learning
- **HDFS log parsing** (notebooks 01–04): Parse → features → train IsolationForest → results
- **Template extraction** (Drain-style), **window features**, **encoder**
- **IsolationForest** model for anomaly detection on HDFS block traces
- **Pipelines**: `train_anomaly.py`, `infer_anomaly.py` (scaffolded)
- **Data**: HDFS_v1 dataset support, processed outputs in `machine_learning/data/`

### 5. Testing & Verification
- **Pipeline verification** (`scripts/verify_pipeline.py`): Heuristic, LLM graceful failure, resume
- **API tests** (`code_testing/test_api.py`), schema contracts, RAG chunker, planner tests

### 6. Documentation & Mockups
- **Docs**: Architecture, pipeline flow, job workflow, RAG design, tech stack
- **Desktop UI mockups** (`docs/desktop_ui_mockups.html`)
- **Mobile UI mockups** (`docs/mobile_ui_mockups.html`)
- **AI roadmap** (`roadmaps/AI_roadmap.html`)

---

## 🔮 To Be Implemented

| Area | Items |
|------|-------|
| **Desktop App** | Interactive desktop app (Electron/Tauri) – mockups exist |
| **Mobile App** | Mobile UI – mockups exist |
| **Log Ingestion** | Automated pipeline for continuous log ingestion |
| **Real-time Monitoring** | Real-time log streaming with alerts |
| **Advanced RCA** | LLM-enhanced root-cause analysis (deeper reasoning) |
| **Visualization** | Dashboard for anomalies, trends, and metrics |
| **ML Integration** | Wire ML anomaly detection into API/agent (train/infer pipelines) |
| **CI/CD** | Intelligent CI/CD pipeline integration |
| **Production API** | Persistent job store, queue (Redis/Celery), auth |

---

## ✨ Key Features  

### 🔹 ErrorSplitter  
Automatically separates logs by error types for focused debugging.

### 🔹 LogSummary  
Generates concise, AI-driven summaries of long and noisy log files.

### 🔹 StackTrace Analyzer  
Simplifies and extracts stack traces for fast root-cause identification.

### 🔹 Error Line Detection (`error_lines`)  
Pinpoints critical failure lines in large logs.

### 🔹 Error Code Search (`error_code`)  
Searches and extracts error codes (HTTP status codes, custom error codes, etc.) from logs.

### 🔹 Log Level Filtering (`filter_log_level`)  
Filters logs by severity levels (ERROR, WARN, INFO, DEBUG, FATAL, etc.).

### 🔹 Keyword-Based Log Search (`search_on_keyword`)  
Searches and highlights logs using specific keywords or patterns.

### 🔹 Time Slicing  
Analyzes log activity within selected time ranges.

### 🔹 Root-Cause Extraction  
Applies AI/ML logic to identify probable causes behind errors.

### 🔹 Unified Utility Interface (`log_utility_main`)  
Centralized entry point providing menu-driven access to all log analysis utilities.

---

## 📂 Dataset Sources  

We use publicly available datasets for training and benchmarking:

- 🔗 https://github.com/logpai/loghub  
- 🔗 https://www.kaggle.com/datasets/ayenuryrr/loghub-hdfs-hadoop-distributed-file-system-data
- 🔗 https://github.com/logpai/loghub

---

## 📂 Project Structure

```text
log-analysis-AI-agent/
├── api/                     # FastAPI backend
│   ├── main.py              # App entry, CORS, middleware
│   ├── routers/             # health, jobs
│   ├── services/            # job_store, runner
│   ├── schemas/             # JobRequest, JobResponse
│   └── core/                # paths, config
├── agent/                   # AI agent (RAG, planning, tools)
│   ├── llm/                 # LLaMA, Ollama clients
│   ├── planner/             # heuristic_planner, llm_planner, planner_router
│   ├── rag/                 # chunker, embedder, retriever, vector_store, index_manager
│   ├── roles/               # retrieval_agent, investigation_agent, reporter_agent
│   └── runtime/             # worker, tool_executor, tool_registry, storage, job_models
├── machine_learning/        # ML anomaly detection
│   ├── data/                # parser, hdfs_loader, labels
│   ├── features/            # templates, vectorize, embeddings
│   ├── models/              # isolation_forest, evaluator
│   ├── pipelines/           # train_anomaly, infer_anomaly
│   └── config.py
├── notebooks/               # ML pipeline notebooks
│   ├── 01_parse_hdfs.ipynb
│   ├── 02_build_features.ipynb
│   ├── 03_train_isoforest.ipynb
│   └── 04_results_isoforest.ipynb
├── utilities/               # Log analysis tools
│   ├── error_code.py        # Search and extract error codes
│   ├── error_lines.py       # Extract specific error lines
│   ├── filter_log_level.py  # Filter logs by log level
│   ├── log_summary.py       # Generate log summaries
│   ├── log_utility_main.py  # Unified CLI entry point
│   ├── search_on_keyword.py # Keyword-based search
│   ├── stacktrace.py        # Stacktrace parsing
│   ├── time_slice.py        # Filter logs by time windows
│   └── retrieve_context.py  # RAG retrieval
├── code_testing/            # Tests (API, pipeline, RAG, utilities)
├── docs/                    # Architecture, mockups, workflows
├── roadmaps/                # AI_roadmap.html
├── scripts/                 # verify_pipeline, run_job, smoke tests
├── data/                    # Input/output logs
├── output/                  # Indexes, vector store
├── runs/                    # Job run data (runs/<job_id>/)
└── README.md
```

## Safety Check

Before deploying or integrating, verify the pipeline is working correctly:

```bash
# Run full pipeline verification (3 scenarios)
python scripts/verify_pipeline.py

# Run smoke test
python -m unittest code_testing.test_pipeline_smoke
```

The verification script checks:
- **Scenario A**: Heuristic end-to-end execution
- **Scenario B**: LLM mode graceful failure handling
- **Scenario C**: Resume/idempotency (artifacts not rerun)

All scenarios must pass for a **GO** status.

## 🚀 Quick Start

### Using the Unified Utility Interface

The easiest way to access all log analysis utilities is through the main interface:

```bash
# Run the main utility interface
python utilities/log_utility_main.py

# Or import as a module
python -m utilities.log_utility_main
```

This provides a menu-driven interface to access:
- Search by Keyword
- Filter by Log Level
- Log Summary
- Extract Stacktraces
- Time Slice
- Search by Error Code
- Get Error Lines

### Using Individual Utilities

You can also import and use individual utilities programmatically:

```python
from utilities.log_utility_main import (
    search_keyword,
    filter_by_log_level,
    summarize_log,
    extract_stacktraces,
    slice_by_time,
    search_by_error_code
)

# Example: Search for keywords
result_file = search_keyword(log_content, "error")

# Example: Filter by log level
error_lines = filter_by_log_level(log_file, "ERROR")

# Example: Generate log summary
summary = summarize_log(log_file)
```

### Running Individual Utility Scripts

Each utility can also be run independently:

```bash
# Filter by log level
python utilities/filter_log_level.py

# Generate log summary
python utilities/log_summary.py

# Extract stacktraces
python utilities/stacktrace.py data/sample.log

# Search by error code
python utilities/error_code.py data/sample.log 503 404
```

---

## 🌐 API Server

The FastAPI server provides REST endpoints for submitting and querying log analysis jobs.

### Running the API Server

```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Run the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Or for production (no auto-reload)
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API Base**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### API Endpoints

- `POST /api/v1/jobs` - Start a new log analysis job
- `GET /api/v1/jobs/{job_id}` - Get job status and summary
- `GET /api/v1/jobs/{job_id}/report` - Get final markdown report
- `GET /api/v1/jobs/{job_id}/artifacts` - List job artifacts
- `GET /api/v1/jobs/{job_id}/artifacts/{artifact_name}` - Download specific artifact

### Example API Usage

```bash
# Start a job
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Why are timeouts happening?",
    "log_path": "data/sample.log",
    "mode": "llm"
  }'

# Check job status
curl http://localhost:8000/api/v1/jobs/{job_id}

# Get final report
curl http://localhost:8000/api/v1/jobs/{job_id}/report
```

---

## ⭐ Vision  

Logs are messy.  
Debugging is slow.  
Our goal: Make log analysis **smarter, faster, and fully automated** using AI.

