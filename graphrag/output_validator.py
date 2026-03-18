"""Validation for LLM explanation output contract."""

from __future__ import annotations

from typing import Any, Mapping


REQUIRED_KEYS = (
    "summary",
    "primary_cause_file_id",
    "confidence",
    "evidence_bullets",
    "limitations",
)


def validate_output(output: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Validate explanation output shape and basic constraints."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in output:
            errors.append(f"missing key: {key}")

    if "summary" in output and not isinstance(output.get("summary"), str):
        errors.append("summary must be string")
    if "primary_cause_file_id" in output and not isinstance(output.get("primary_cause_file_id"), str):
        errors.append("primary_cause_file_id must be string")

    conf = output.get("confidence")
    if not isinstance(conf, (int, float)):
        errors.append("confidence must be numeric")
    elif conf < 0 or conf > 1:
        errors.append("confidence must be in [0,1]")

    eb = output.get("evidence_bullets")
    if not isinstance(eb, list) or not all(isinstance(x, str) for x in eb):
        errors.append("evidence_bullets must be list[str]")
    elif len(eb) == 0 or len(eb) > 6:
        errors.append("evidence_bullets must contain 1..6 entries")

    lim = output.get("limitations")
    if not isinstance(lim, list) or not all(isinstance(x, str) for x in lim):
        errors.append("limitations must be list[str]")
    elif len(lim) == 0 or len(lim) > 5:
        errors.append("limitations must contain 1..5 entries")

    return (len(errors) == 0, errors)
