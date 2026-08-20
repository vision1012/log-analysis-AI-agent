# GraphRAG Explanation Output Contract

Defines the required LLM explanation output for graph-based RCA.

## Output Format

Primary output MUST be a single JSON object.

Optional: a short human-readable rendering may be generated downstream from this JSON, but JSON is the source of truth.

## Required JSON Shape

```json
{
  "anomaly_id": "string",
  "primary_candidate": {
    "rank": 1,
    "file_id": "string",
    "path": "string",
    "confidence": 0.0,
    "evidence_ref": "string"
  },
  "ranked_hypotheses": [
    {
      "rank": 1,
      "file_id": "string",
      "path": "string",
      "confidence": 0.0,
      "hypothesis": "string",
      "evidence_ref": "string"
    }
  ],
  "explanation_summary": "string",
  "evidence_highlights": ["string"],
  "confidence_alignment_note": "string",
  "optional_patch_direction": "string",
  "limitations": "string"
}
```

## Field Requirements

- `anomaly_id`:
  - Required string.
  - Must match the input context `anomaly_id`.

- `primary_candidate`:
  - Required object.
  - Must correspond to one entry in deterministic RCA candidates.
  - `rank` must be the deterministic top rank (normally `1`).

- `ranked_hypotheses`:
  - Required array, length `>= 1`.
  - Must be ordered exactly by deterministic RCA rank (no reordering).
  - Every `file_id` and `path` must exist in deterministic RCA context.
  - `confidence` must match or round from deterministic candidate confidence.

- `explanation_summary`:
  - Required narrative summary of why the deterministic top candidate is most likely.
  - **Target length:** 4–5 complete sentences (~80–120 words) in **one short paragraph** of plain text.
  - **Recommended bounds:** minimum ~60 words / ~240 characters for UI quality; maximum ~800 characters.
  - **Format:** plain text only — no Markdown headings, bullet lists, or embedded JSON inside this field.
  - **Required coverage (in order):**
    1. Incident context from ticket, logs, and stack trace (do not overemphasize missing ticket data).
    2. Selected candidate with normalized path/component and deterministic confidence when provided.
    3. Why it ranked first, citing the strongest 2–4 available signals in natural language.
    4. A grounded interpretation of what likely happened, clearly labeled as interpretation where needed.
    5. Relevant uncertainty or missing evidence without fabricating facts.
  - **Must not include:** remediation steps, patch instructions, or reranking language (those belong in `optional_patch_direction` or `limitations`).
  - Downstream UI and orchestration may treat summaries below the minimum bounds as non-substantive and fall back to deterministic template text.

- `evidence_highlights`:
  - Required list of concise factual bullets from graph-derived evidence.
  - Recommended length: `1..8`.
  - Must reference available signals/commit/deployment/recurrence evidence only.

- `confidence_alignment_note`:
  - Required statement explaining alignment between narrative confidence and deterministic score ordering.
  - Must explicitly acknowledge deterministic ranking as source of truth.

- `optional_patch_direction`:
  - Required string field.
  - May be empty string if no safe patch direction is inferable from evidence.
  - Must remain high-level (no proprietary code dump).

- `limitations` (alias: `limitations_or_uncertainty`):
  - Required uncertainty/limitation note as a single string.
  - Must mention missing/weak evidence when applicable.

## Deterministic Guardrails (Mandatory)

1. The LLM MUST NOT introduce files, candidate IDs, or hypotheses absent from deterministic RCA results.
2. Deterministic ranking remains the source of truth for candidate ordering.
3. The LLM may explain ranking but may not override it.
4. If explanation confidence language conflicts with deterministic scores, `confidence_alignment_note` must call this out explicitly.

## Evidence Scope Constraints

- No raw logs unless strictly required and explicitly provided in context.
- No proprietary full-code blobs.
- No fabricated commit/deployment references.
- `evidence_ref` values must map to known persisted bundles from context.

## Validation Checklist

An explanation is valid only if all conditions hold:

- all required keys present,
- `anomaly_id` matches context,
- every hypothesis candidate exists in deterministic context,
- ranked order equals deterministic order,
- `primary_candidate` equals top deterministic candidate,
- guardrail and evidence scope constraints are satisfied.
