"""Build system/user prompts for graph-grounded RCA explanation."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional


SYSTEM_PROMPT = (
    "You explain RCA results from graph-grounded evidence only. "
    "Do not invent missing data. If evidence is weak or incomplete, say so clearly. "
    "Return strict JSON with keys: summary, primary_cause_file_id, confidence, "
    "evidence_bullets, limitations."
)


def build_prompt(
    context_pack: Mapping[str, Any],
    evidence_bullets: list[str],
    *,
    user_instruction: Optional[str] = None,
) -> dict[str, str]:
    """Create prompt payload for an LLM client."""
    instruction = user_instruction or "Explain the most likely root cause for this anomaly."
    payload = {
        "instruction": instruction,
        "context": context_pack,
        "evidence_bullets": evidence_bullets,
        "output_contract": {
            "summary": "string <= 600 chars",
            "primary_cause_file_id": "string",
            "confidence": "float [0,1]",
            "evidence_bullets": "list[string] 1..6",
            "limitations": "list[string] 1..5",
        },
    }
    return {
        "system": SYSTEM_PROMPT,
        "user": json.dumps(payload, ensure_ascii=True, indent=2),
    }
