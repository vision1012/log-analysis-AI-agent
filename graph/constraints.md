# Uniqueness and Indexing Strategy

This document defines the uniqueness constraints and indexing strategy for the Neo4j Knowledge Graph.

---

## Uniqueness Constraints

Each node label enforces uniqueness on its primary identifier:

| Label | Unique Property | Purpose |
|-------|-----------------|---------|
| LogSource | id | Prevent duplicate sources |
| LogTemplate | id | Prevent duplicate templates |
| LogEvent | id | Prevent duplicate events |
| Anomaly | id | Prevent duplicate anomaly records |
| Job | id | Prevent duplicate jobs |
| Investigation | id | Prevent duplicate investigation steps |

---

## Indexing Strategy

### Primary Lookup Indexes

Create indexes on the unique `id` property for each label to support fast node lookup and constraint enforcement.

| Label | Indexed Property | Type |
|-------|------------------|------|
| LogSource | id | UNIQUE |
| LogTemplate | id | UNIQUE |
| LogEvent | id | UNIQUE |
| Anomaly | id | UNIQUE |
| Job | id | UNIQUE |
| Investigation | id | UNIQUE |

### Query-Optimization Indexes

Additional indexes for common query patterns:

| Label | Property | Use Case |
|-------|----------|----------|
| LogEvent | timestamp | Time-range queries |
| LogEvent | log_level | Filter by severity |
| Anomaly | window_id | Window-based lookups |
| Job | status | Status filtering |
| Job | created_at | Chronological queries |

---

## Implementation Notes

- Constraints and indexes should be created at graph initialization
- Use `CREATE CONSTRAINT ... IF NOT EXISTS` for idempotent setup
- Use `CREATE INDEX ... IF NOT EXISTS` for non-constraint indexes
