# `graphrag/` — GraphRAG pipeline (LLM-assisted explanation layer)

Builds prompts and optional LLM calls **on top of** graph context and evidence. Does **not** replace deterministic RCA; it summarizes or explains RCA outputs.

| File | Purpose |
|------|---------|
| `context_packer.py` | Packs graph + evidence into a bounded context for the LLM. |
| `prompt_builder.py` | Constructs prompts from templates and packed context. |
| `llm_client.py` | Invokes configured LLM provider (Ollama/OpenAI/stub) |
| `evidence_summarizer.py` | Summarizes evidence snippets for inclusion in prompts or UI. |
| `explanation_generator.py` | Produces natural-language explanations from structured RCA output. |
| `output_validator.py` | Validates LLM output shape against contracts. |
| `__init__.py` | Package marker. |

| Subfolder | Purpose |
|-----------|---------|
| `specs/` | Markdown contracts: context shape, explanation output, guardrails. |
