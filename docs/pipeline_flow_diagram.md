# Log Analysis AI Agent – Pipeline Flow (High Level)

## Pipeline Overview

```mermaid
flowchart LR
    Client([Client]) -->|Submit job| API[API]
    API -->|Create & queue| Storage[(Storage)]
    API -->|Run in background| Pipeline[Pipeline]

    Pipeline --> Mode{Mode?}
    Mode -->|RAG| RAG[Retrieve → Investigate → Report]
    Mode -->|Heuristic| Heur[Plan → Run Tools]

    RAG --> Artifacts[Artifacts]
    Heur --> Artifacts
    Artifacts -->|Save & register| Storage
    Storage -->|Get job / report| Client
```

## End-to-End Flow

```mermaid
flowchart TD
    A([Request]) --> B[API]
    B --> C[Create Job]
    C --> D[Run Pipeline]
    D --> E{Mode?}
    E -->|RAG| F[Retrieve context]
    F --> G[Investigate]
    G --> H[Generate report]
    E -->|Heuristic| I[Plan tools]
    I --> J[Execute tools]
    J --> K[Build answer]
    H --> L[Save results]
    K --> L
    L --> M([Response])
```

## What Each Stage Does

| Stage | Purpose |
|-------|--------|
| **API** | Accepts question + log path, creates job, returns job ID, runs pipeline in background. |
| **Create Job** | Persists job (queued), assigns ID, stores in runs. |
| **Run Pipeline** | Validates input, picks mode (RAG vs Heuristic), runs the chosen path. |
| **RAG path** | Retrieve (vector search on logs) → Investigate (LLM analysis) → Generate report. |
| **Heuristic path** | Plan (keyword-based tool selection) → Execute tools → Build answer. |
| **Save results** | Writes artifacts, updates job status (succeeded/failed/cancelled), registers artifact paths. |
| **Response** | Client polls or fetches job; gets status, report, and artifact metadata. |

## One-Line Summary

**Request → API creates job → Pipeline runs (RAG: retrieve → investigate → report, or Heuristic: plan → run tools) → Results saved → Client gets job/report.**
