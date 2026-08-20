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

## Explanation narrative (UI target)

Assistive explanations are meant to read as a **short incident narrative**, not a one-line label.

| Aspect | Guidance |
|--------|----------|
| Length | 4–5 sentences (~80–120 words) |
| Shape | One plain-text paragraph in `explanation_summary` |
| Source of truth | Deterministic RCA ranking and packed evidence only |
| Quality floor | Summaries shorter than ~60 words may be rejected and replaced with a safe fallback |

Authoritative field rules live in [`specs/explanation_output_contract.md`](specs/explanation_output_contract.md). Prompt strings in `prompt_builder.py` and validation thresholds in `output_validator.py` / orchestration should stay aligned with that contract.
