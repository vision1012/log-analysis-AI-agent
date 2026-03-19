# Debug Agent Output Contract

Defines the unified investigation report structure for the debug agent orchestration layer.

## Investigation Report (Final Output)

The debug session produces a single **Investigation Report** with this shape:

```json
{
  "anomaly_id": "string",
  "run_id": "string | null",
  "created_at": "string",
  "status": "completed | partial | failed",
  "triage_summary": "string",
  "root_cause_candidates": [
    {
      "rank": 1,
      "file_id": "string",
      "path": "string",
      "confidence": 0.0,
      "evidence_ref": "string"
    }
  ],
  "primary_candidate": {
    "rank": 1,
    "file_id": "string",
    "path": "string",
    "confidence": 0.0,
    "evidence_ref": "string"
  },
  "confidence_summary": "string",
  "evidence_highlights": ["string"],
  "similar_incidents": [
    {
      "anomaly_id": "string",
      "summary": "string",
      "prior_count": 0
    }
  ],
  "explanation_summary": "string",
  "remediation_steps": ["string"],
  "optional_patch_direction": "string",
  "final_report_summary": "string"
}
```

## Field Requirements

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `anomaly_id` | string | Yes | Unique anomaly identifier |
| `run_id` | string \| null | Yes | RCA run identifier |
| `created_at` | string | Yes | ISO-8601 timestamp when report was created |
| `status` | enum | Yes | `completed`, `partial`, or `failed` |
| `triage_summary` | string | Yes | Brief triage/priority assessment |
| `root_cause_candidates` | array | Yes | Ranked candidates from deterministic RCA |
| `primary_candidate` | object | Yes | Top candidate (rank 1) |
| `confidence_summary` | string | Yes | Alignment note for confidence values |
| `evidence_highlights` | array[string] | Yes | Factual bullets from graph evidence |
| `similar_incidents` | array | Yes | Prior incidents linked to same files |
| `explanation_summary` | string | Yes | Natural-language explanation |
| `remediation_steps` | array[string] | Yes | Ordered advisory steps |
| `optional_patch_direction` | string | Yes | High-level patch hint (advisory only) |
| `final_report_summary` | string | Yes | Concise executive summary |

## Candidate Object

Each `root_cause_candidates` entry and `primary_candidate` must include:

- `rank` (integer): 1-based deterministic rank
- `file_id` (string): Attributed file identifier
- `path` (string): Repo-relative file path
- `confidence` (number): Score in [0, 1]
- `evidence_ref` (string): Pointer to evidence bundle

## Similar Incident Object

- `anomaly_id` (string): Prior anomaly ID
- `summary` (string): Brief description
- `prior_count` (integer): Count of prior attributions for this file

## Constraints

- Deterministic RCA remains source of truth.
- No invented candidates or evidence.
- `primary_candidate` must equal top entry in `root_cause_candidates`.
- Patch/remediation content must be advisory only.
- Output must be JSON-serializable; no raw proprietary code or full logs.
