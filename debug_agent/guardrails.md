# Debug Agent Guardrails

Hard rules for the debug agent orchestration layer.

---

## Strict Rules (Mandatory)

### 1) RCA Authority

- **Deterministic RCA is the source of truth.** All candidate ranking, file attribution, and confidence scores come from the deterministic RCA engine. No agent may override or replace these values.

### 2) No Override of Ranking

- **No agent can override RCA ranking.** The order of `root_cause_candidates` and the identity of `primary_candidate` are fixed by deterministic RCA. Agents may explain, summarize, or annotate—but never reorder, demote, or promote candidates.

### 3) No Hallucination

- **No hallucinated files, commits, or incidents.** Agents must not invent:
  - File paths or file_ids not present in deterministic RCA results
  - Commit SHAs, deployment IDs, or timestamps not in graph or evidence bundles
  - Prior incidents or recurrence counts not derivable from graph queries
  - Evidence bullets not grounded in structured evidence

### 4) LLM Grounding

- **LLM agents must only use grounded inputs.** Any agent that uses an LLM must receive:
  - Packed context from deterministic RCA and evidence bundles
  - No free-form prompts that invite fabrication
  - Output validation against the allowed candidate set before returning

### 5) Advisory Patch Only

- **Patch suggestions are advisory only.** Remediation and explanation agents must:
  - Label patch direction as advisory, suggested, or consider
  - Never present a patch as a guaranteed fix
  - Keep suggestions high-level; no prescriptive code replacement

### 6) No Auto-Fix

- **No auto-fix behavior.** The system does not:
  - Apply patches automatically
  - Modify code, config, or deployments
  - Execute remediation steps without explicit user action

### 7) LLM Failure Resilience

- **System must work even if LLM fails.** When an LLM-assisted agent fails or times out:
  - Return a safe fallback built from deterministic evidence only
  - Do not block the session; continue with partial results
  - Mark status as `partial` when fallback is used

### 8) Safe Agent Failure

- **Each agent must fail safely and return partial results.** On error:
  - Return a `StepResult` with `success=False` and a clear `error` message
  - Do not raise uncaught exceptions that abort the session
  - Orchestrator aggregates whatever results are available and produces a report with `status: partial` or `status: failed` as appropriate

---

## Agent Classification

### Deterministic Agents

Agents that use only graph queries, evidence bundles, and deterministic RCA outputs. No LLM. Output is fully reproducible given the same inputs.

| Agent | Description |
|-------|-------------|
| **RCA** | Calls deterministic RCA engine. Returns candidates and ranking as-is. No modification. |
| **Evidence** | Reads evidence bundles and graph-derived signals. Produces structured bullets. No LLM. |
| **Memory** | Queries graph for prior attributions, similar incidents, recurrence counts. Returns structured data only. No LLM. |
| **Reporting** | Aggregates outputs from other agents into the Investigation Report. Pure aggregation and formatting. No LLM. |

### LLM-Assisted Agents

Agents that may use an LLM to generate natural language. Must receive grounded context and validate output.

| Agent | Description |
|-------|-------------|
| **Explanation** | Uses GraphRAG explanation layer. Receives packed context and evidence bullets. Output validated against deterministic candidates. |
| **Remediation** | May use LLM to suggest advisory patch direction. Must receive only grounded inputs (candidates, evidence). Output must be marked advisory. |
| **Triage** | May use LLM for priority/classification. Must use only anomaly metadata and deterministic RCA results as input. Output must not influence ranking. |

---

## What Each Agent Is Allowed To Do

### RCA Agent

- **Allowed:** Call deterministic RCA, return candidates and ranking unchanged.
- **Not allowed:** Re-rank, filter, or modify candidates; invent new candidates.

### Evidence Agent

- **Allowed:** Read evidence bundles and graph; produce structured evidence bullets; summarize signals.
- **Not allowed:** Invent evidence; cite files/commits not in bundles; include raw code or full logs.

### Explanation Agent

- **Allowed:** Generate natural-language explanation from packed context; cite deterministic candidates; align wording with confidence scores; provide optional advisory patch hint.
- **Not allowed:** Re-rank; introduce new candidates; overstate confidence; present patch as guaranteed fix.

### Triage Agent

- **Allowed:** Classify priority; produce triage summary from anomaly metadata and RCA results.
- **Not allowed:** Change RCA ranking; invent severity; influence which candidates are shown.

### Memory Agent

- **Allowed:** Query graph for prior attributions; return similar incidents; compute recurrence counts per file.
- **Not allowed:** Invent prior incidents; fabricate recurrence; return data not from graph.

### Remediation Agent

- **Allowed:** Suggest advisory remediation steps; provide high-level patch direction; list ordered steps.
- **Not allowed:** Present fixes as guaranteed; prescribe exact code; auto-apply changes.

### Reporting Agent

- **Allowed:** Aggregate agent outputs into Investigation Report; format fields; produce final summary.
- **Not allowed:** Override any deterministic field; invent report content; change candidate order.

---

## Isolation

- Do not import from `old_log_arch_v1`.
- Keep orchestration thin over the active RCA platform.
- Fail gracefully when upstream services (Neo4j, evidence store, LLM) are unavailable.
