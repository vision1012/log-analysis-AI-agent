# GraphRAG Guardrails (Hard Rules)

Defines mandatory constraints for the LLM explanation layer in the graph-based RCA platform.

## 1) Candidate Integrity Guardrails

1. The model MUST NOT invent or mention any file/candidate not present in deterministic RCA context.
2. Every mentioned candidate `file_id` and `path` MUST map to provided deterministic candidates.
3. Evidence pointers (`evidence_ref`) MUST come only from provided context.

## 2) Ranking Authority Guardrails

1. Deterministic ranking is the source of truth.
2. The model MUST NOT reorder candidates.
3. The model MAY explain why rank #1 is likely, but MUST preserve rank order exactly.

## 3) Confidence Claim Guardrails

1. The model MUST NOT claim certainty beyond deterministic confidence evidence.
2. Absolute language (e.g., "definitive", "certain", "guaranteed") is disallowed unless deterministic confidence and policy explicitly permit it.
3. Narrative confidence must align with deterministic scores and include caveats when evidence is partial.

## 4) Patch Suggestion Guardrails

1. Any fix/patch direction MUST be labeled as advisory.
2. The model MUST NOT present patch guidance as confirmed root-cause remediation.
3. Patch guidance should be high-level and evidence-linked, not prescriptive code replacement.

## 5) Proprietary Content Guardrails

1. The model MUST NOT quote full proprietary code bodies.
2. Do not emit large source snippets.
3. Use identifiers, paths, and compact evidence summaries instead of code dumps.

## 6) Incomplete Evidence Guardrails

1. When evidence is missing or weak, the model MUST degrade gracefully.
2. Output MUST include explicit uncertainty/limitations.
3. If validation fails or evidence is insufficient, return fallback-safe explanation with low confidence and clear caveats.

## 7) Post-Generation Validation Checks (Mandatory)

These checks must run after generation and before returning output:

1. **Schema check**
   - required output fields exist and types match contract.

2. **Candidate membership check**
   - all candidates in output exist in deterministic RCA input set.

3. **Ranking consistency check**
   - output ranking exactly matches deterministic rank order.

4. **Confidence bounds check**
   - confidence values are numeric and in `[0,1]`.
   - confidence wording is not stronger than deterministic score context.

5. **Advisory patch check**
   - patch direction (if present) is explicitly advisory.

6. **Proprietary leakage check**
   - no full-code blobs, no raw log dumps, no secret-like payloads.

7. **Uncertainty check**
   - limitations/uncertainty note is present when evidence completeness is low.

## 8) Failure Handling Policy

If any mandatory validation check fails:

1. Do not return raw model output.
2. Return a safe fallback explanation:
   - preserve deterministic top candidate metadata,
   - set conservative confidence,
   - include validation-failure limitation note.
3. Log validation failure reason for observability.
