"""
Deterministic RCA runner. Delegates to rca_runner.run_deterministic_rca.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from graphrag.llm_client import GraphRAGLLMClient
from rca_engine.rca_runner import RCARunResult, run_deterministic_rca as _run_deterministic_rca

if TYPE_CHECKING:
    from graph.neo4j_client import Neo4jClient
    from graph.writer import GraphWriter
    from artifacts.evidence_store import EvidenceStore


def run_llm_explanation(rca_output: dict[str, Any], signals: dict[str, Any], logs: list[str]) -> dict[str, Any]:
    prompt = f"""
    You are an SRE assistant.

    RCA Result:
    {rca_output}

    Signals:
    {signals}

    Logs:
    {logs[:20]}

    Explain:
    - What is happening
    - Why it is happening
    - Suggested fix
    """
    llm_client = GraphRAGLLMClient()
    print("[LLM] Prompt:", prompt)
    response = llm_client.generate(system_prompt="You are an SRE assistant.", user_prompt=prompt)
    print("[LLM] Response:", response)
    return response


def run_deterministic_rca(
    anomaly_id: str,
    trigger_type: str,
    *,
    graph_client: "Neo4jClient",
    graph_writer: "GraphWriter",
    evidence_store: "EvidenceStore",
    run_id: Optional[str] = None,
    override: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute deterministic RCA for one anomaly.

    Delegates to rca_runner.run_deterministic_rca.
    """
    print("[RCA] Starting RCA run")
    log_lines = kwargs.get("log_lines")
    if isinstance(log_lines, list):
        print(f"[RCA] Total log lines: {len(log_lines)}")
    else:
        print("[RCA] Total log lines: 0")

    result = _run_deterministic_rca(
        anomaly_id,
        trigger_type,
        graph_client=graph_client,
        graph_writer=graph_writer,
        evidence_store=evidence_store,
        run_id=run_id,
        override=override,
        **kwargs,
    )
    ranked_count = result.attribution_count if result is not None else 0
    print(f"[RCA] Ranked candidates: {ranked_count}")

    ranked_candidates = kwargs.get("ranked_candidates")
    if not isinstance(ranked_candidates, list):
        ranked_candidates = []

    signals = kwargs.get("signals")
    if not isinstance(signals, dict):
        signals = {}

    # Normalize signal keys expected by the final RCA response.
    timeout_count = int(signals.get("timeout_count", signals.get("timeout", 0)) or 0)
    normalized_signals = {
        "error_count": int(signals.get("error_count", 0) or 0),
        "timeout_count": timeout_count,
        "invalid_token_count": int(signals.get("invalid_token_count", 0) or 0),
        **signals,
    }

    candidates: list[dict[str, Any]] = []
    for c in ranked_candidates:
        if isinstance(c, dict):
            candidates.append(
                {
                    "value": c.get("value") or c.get("path") or c.get("file_id"),
                    "score": c.get("score", c.get("confidence", 0)),
                    **c,
                }
            )
        else:
            candidates.append(
                {
                    "value": getattr(c, "value", "") or getattr(c, "path", "") or getattr(c, "file_id", ""),
                    "score": getattr(c, "score", 0),
                }
            )

    output = {
        "primary_root_cause": candidates[0]["value"] if candidates else None,
        "confidence": candidates[0]["score"] if candidates else 0,
        "evidence": normalized_signals,
        "candidates": candidates,
        "explanation": "Generated based on log signals",
    }
    _ = run_llm_explanation(output, normalized_signals, log_lines if isinstance(log_lines, list) else [])
    return output
