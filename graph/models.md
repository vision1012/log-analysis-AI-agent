# Node Definitions (No Relationships)

This document defines node labels and properties for the Knowledge Graph. Relationships are not yet specified.

---

## LogSource

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier |
| path | string | File path or stream identifier |
| source_type | string | `file`, `stream`, `system` |
| created_at | datetime | Creation timestamp |

---

## LogTemplate

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier |
| template_str | string | Parsed template string |
| event_type | string | Optional event classification |
| created_at | datetime | Creation timestamp |

---

## LogEvent

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier |
| raw_line | string | Original log line |
| log_level | string | `INFO`, `WARN`, `ERROR`, etc. |
| timestamp | datetime | Event timestamp |
| created_at | datetime | Record creation timestamp |

---

## Anomaly

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier |
| score | float | Anomaly score |
| window_id | string | Time window identifier |
| created_at | datetime | Detection timestamp |

---

## Job

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier (UUID) |
| status | string | `pending`, `running`, `completed`, `failed` |
| mode | string | `heuristic`, `rag`, `llm` |
| created_at | datetime | Job creation timestamp |

---

## Investigation

| Property | Type | Description |
|----------|------|-------------|
| id | string | Unique identifier |
| step_type | string | Type of investigation step |
| created_at | datetime | Step timestamp |
