# Temporal Modeling Rules

This document defines the temporal modeling rules for the Knowledge Graph.

---

## Timestamp Conventions

| Field | Meaning | Format |
|-------|---------|--------|
| timestamp | When the event/occurrence happened (domain time) | ISO 8601 |
| created_at | When the record was added to the graph | ISO 8601 |

---

## Rules

### 1. Event Time vs. Record Time

- **Event time** (`timestamp`): The actual time of the log event or anomaly in the source system
- **Record time** (`created_at`): When the node was ingested into the graph

Both must be stored where applicable. Nodes without domain time (e.g., static templates) may omit `timestamp` but should retain `created_at`.

### 2. Time Windows

- Anomalies and batched analyses reference a `window_id` representing a time window
- Window boundaries are defined externally (e.g., by the ML pipeline); the graph stores the reference only

### 3. Ordering

- Temporal ordering of events is inferred from `timestamp` when present
- Use `timestamp` for time-slice queries and causal reasoning
- Use `created_at` for audit and ingestion ordering

### 4. Time Zones

- All timestamps are stored in UTC
- Conversion to local time is handled at query or presentation layer

### 5. Null Handling

- `created_at` is required for all nodes
- `timestamp` is optional for nodes that do not represent point-in-time events (e.g., LogTemplate, LogSource)
