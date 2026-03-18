"""Pack RCA graph outputs into a compact LLM context payload."""

from __future__ import annotations

from typing import Any, Mapping, Optional


def _truncate_text(value: Any, max_len: int = 240) -> str:
    s = str(value or "")
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _pack_candidates(
    candidates: list[Mapping[str, Any]],
    *,
    max_candidates: int,
    max_signal_entries: int,
) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    for c in candidates[:max_candidates]:
        signal_scores = c.get("signal_scores") or {}
        signal_items = sorted(
            signal_scores.items(),
            key=lambda kv: float(kv[1]) if isinstance(kv[1], (int, float)) else 0.0,
            reverse=True,
        )[:max_signal_entries]
        packed.append(
            {
                "file_id": c.get("file_id"),
                "path": _truncate_text(c.get("path")),
                "run_id": c.get("run_id"),
                "confidence": c.get("confidence"),
                "evidence_ref": c.get("evidence_ref"),
                "top_signals": [{"name": k, "score": v} for k, v in signal_items],
            }
        )
    return packed


def pack_context(
    anomaly_id: str,
    *,
    result_view: Mapping[str, Any],
    run_summary: Optional[Mapping[str, Any]] = None,
    evidence_bundles: Optional[Mapping[str, Mapping[str, Any]]] = None,
    max_candidates: int = 3,
    max_signal_entries: int = 6,
) -> dict[str, Any]:
    """
    Build a compact, model-ready context object from RCA outputs.

    Inputs are intentionally generic mappings so callers can pass API/service outputs
    without tight coupling to a single module.
    """
    candidates = result_view.get("candidate_root_causes") or []
    accepted = result_view.get("accepted_root_cause")
    packed_candidates = _pack_candidates(
        candidates,
        max_candidates=max_candidates,
        max_signal_entries=max_signal_entries,
    )

    bundle_map = evidence_bundles or {}
    bundle_brief: list[dict[str, Any]] = []
    for c in packed_candidates:
        ref = c.get("evidence_ref")
        b = bundle_map.get(ref or "", {})
        if not b:
            continue
        bundle_brief.append(
            {
                "bundle_id": ref,
                "attributed_file_id": b.get("attributed_file_id"),
                "attributed_frame_id": b.get("attributed_frame_id"),
                "deployment_id": b.get("deployment_id"),
                "last_touch_commit_sha": b.get("last_touch_commit_sha"),
            }
        )

    return {
        "anomaly_id": anomaly_id,
        "current_status": result_view.get("current_status"),
        "latest_run_id": result_view.get("latest_run_id"),
        "last_updated_at": result_view.get("last_updated_at"),
        "accepted_root_cause": accepted,
        "candidate_root_causes": packed_candidates,
        "run_summary": dict(run_summary or {}),
        "evidence_bundle_brief": bundle_brief,
    }
