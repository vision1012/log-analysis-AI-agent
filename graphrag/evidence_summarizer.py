"""Summarize packed graph evidence into short explanation bullets."""

from __future__ import annotations

from typing import Any, Mapping


def summarize_evidence(context_pack: Mapping[str, Any], *, max_bullets: int = 6) -> list[str]:
    """
    Produce terse, deterministic bullets from packed RCA context.

    These bullets are designed to be fed into the explanation prompt so the model
    grounds output in graph facts.
    """
    bullets: list[str] = []
    candidates = context_pack.get("candidate_root_causes") or []
    if not candidates:
        return ["No current RCA candidates are available for this anomaly."]

    for c in candidates:
        path = c.get("path") or c.get("file_id") or "unknown file"
        conf = c.get("confidence")
        conf_txt = f"{float(conf):.2f}" if isinstance(conf, (int, float)) else "n/a"
        signals = c.get("top_signals") or []
        signal_label = ", ".join(
            f"{s.get('name')}={s.get('score')}" for s in signals[:3]
        ) or "no signal details"
        bullets.append(f"Candidate {path} (confidence {conf_txt}); key signals: {signal_label}.")
        if len(bullets) >= max_bullets:
            break

    accepted = context_pack.get("accepted_root_cause")
    if accepted:
        bullets.append(
            f"Accepted root cause already exists for file_id={accepted.get('file_id')}."
        )
    return bullets[:max_bullets]
