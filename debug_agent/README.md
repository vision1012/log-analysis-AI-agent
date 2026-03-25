# `debug_agent/` — multi-agent debug pipeline

LangChain-assisted **investigation** pipeline: triage, evidence, RCA wrapper, explanation, remediation, reporting. Orchestrated end-to-end from `debug_agent/orchestrator.py` and exposed via `api/debug_agent_routes.py`.

| File | Purpose |
|------|---------|
| `orchestrator.py` | Runs the full debug session: phases, artifact paths, error handling. |
| `planner.py` | Planning / step routing for the investigation. |
| `triage_agent.py` | Initial triage of anomaly/logs. |
| `evidence_agent.py` | Gathers and structures evidence. |
| `memory_agent.py` | Short-term memory / context for the session. |
| `rca_agent.py` | Bridges to deterministic RCA where applicable. |
| `explanation_agent.py` | Explanation step (may use GraphRAG/LLM). |
| `remediation_agent.py` | Suggested remediation narrative or actions. |
| `reporting_agent.py` | Final structured report for API/UI. |
| `tool_registry.py` | Registers tools for agents. |
| `langchain_utils.py` | Shared LangChain helpers (messages, parsers). |
| `langchain_schemas.py` | Pydantic/structured output schemas for agent IO. |
| `shared_types.py` | Shared types across agents. |
| `__init__.py` | Package marker. |

**Separation:** Deterministic RCA logic remains in **`rca_engine/`**; this package **coordinates** agents and tools.
