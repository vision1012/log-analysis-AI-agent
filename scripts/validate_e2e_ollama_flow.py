#!/usr/bin/env python3
"""
End-to-end validation helper for the debug pipeline + RCA + explanation (Ollama optional).

Prerequisites:
  - API running (e.g. uvicorn api.main:app --port 8000)
  - Neo4j contains at least one real anomaly node
  - PostgreSQL: users seeded (scripts/seed_users.py) for POST /api/v1/jobs
  - For Ollama-assisted explanation/remediation/reporting: OLLAMA_HOST, OLLAMA_MODEL, pull model

Usage (repo root)::

    export API_BASE=http://127.0.0.1:8000
    export OLLAMA_HOST=http://localhost:11434   # optional
    python scripts/validate_e2e_ollama_flow.py

Checks:
  - GET /api/v1/rca/results (deterministic baseline)
  - GET /api/v1/rca/explanation (GraphRAG assistive layer)
  - Optional POST /api/v1/jobs (set SKIP_JOB=1 to skip if no Postgres user)
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# Same stable UUID as scripts/seed_users.py for logical user_001
_USER_001 = str(uuid.uuid5(uuid.NAMESPACE_URL, "log-analysis-ai-agent:seed:user_001"))


def _get(url: str, timeout: float = 120.0) -> dict[str, Any]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, body: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _top_rca_fingerprint(rca: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    """Stable tuple for comparing deterministic RCA top candidate (no RCA logic changes)."""
    cands = rca.get("candidates") or []
    if not cands or not isinstance(cands, list):
        return None
    top = cands[0]
    if not isinstance(top, dict):
        return None
    fid = str(top.get("file_id") or "")
    path = str(top.get("path") or "")
    conf = str(top.get("confidence") if top.get("confidence") is not None else "")
    return (fid, path, conf)


def _env_ollama_host_set() -> bool:
    return bool(os.environ.get("OLLAMA_HOST", "").strip())


def _graphrag_provider_expected() -> str:
    raw = os.environ.get("GRAPHRAG_LLM_PROVIDER", "").strip().lower()
    if raw:
        return raw
    return "ollama" if _env_ollama_host_set() else "stub"


def main() -> int:
    base = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
    anomaly_id = os.environ.get("VALIDATE_ANOMALY_ID", "anomaly_001")
    skip_job = os.environ.get("SKIP_JOB", "").strip().lower() in {"1", "true", "yes"}

    print("=== E2E validation (RCA + GraphRAG explanation + optional Ollama) ===")
    print(f"API_BASE={base}  anomaly_id={anomaly_id}")
    print(
        f"OLLAMA_HOST={os.environ.get('OLLAMA_HOST', '(unset)')}  "
        f"GRAPHRAG_LLM_PROVIDER={os.environ.get('GRAPHRAG_LLM_PROVIDER', '(unset)')}"
    )
    print(
        "Expected (heuristic): graphrag LLM provider="
        f"{_graphrag_provider_expected()}"
    )
    print()

    # 1) Health
    try:
        h = _get(f"{base}/health")
        print("[1] GET /health ->", "ok" if h else h)
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        print("[1] GET /health FAILED:", e)
        return 1

    # 1b) Assistive LLM / Ollama runtime (GraphRAG explanation path)
    try:
        llm = _get(f"{base}/health/llm", timeout=15.0)
        print("[1b] GET /health/llm ->")
        print("    graphrag_effective_provider:", llm.get("graphrag_effective_provider"))
        print("    ollama_base_url:", llm.get("ollama_base_url"))
        print("    ollama_reachable:", llm.get("ollama_reachable"), "|", llm.get("ollama_probe_detail"))
        assist = llm.get("assistive") or {}
        print("    assistive_live_expected:", assist.get("assistive_live_expected"))
    except HTTPError as e:
        if e.code == 404:
            print("[1b] GET /health/llm -> 404 (rebuild/restart API image to enable this endpoint)")
        else:
            print("[1b] GET /health/llm FAILED:", e)
            return 1
    except (URLError, TimeoutError, OSError) as e:
        print("[1b] GET /health/llm FAILED:", e)
        return 1

    # 2) Optional job
    if not skip_job:
        try:
            job_body = {
                "job_type": "e2e_validate",
                "anomaly_id": anomaly_id,
                "run_id": f"run_e2e_{anomaly_id}",
                "triggered_by_user_id": _USER_001,
                "trigger_source": "validate_e2e_ollama_flow",
            }
            job = _post(f"{base}/api/v1/jobs", job_body, timeout=30.0)
            print("[2] POST /api/v1/jobs -> job_id=", job.get("job_id"), "status=", job.get("status"))
        except HTTPError as e:
            print("[2] POST /api/v1/jobs SKIPPED/FAILED (set SKIP_JOB=1 to skip):", e.read().decode()[:300])
        except Exception as e:
            print("[2] POST /api/v1/jobs FAILED:", e)
    else:
        print("[2] POST /api/v1/jobs skipped (SKIP_JOB=1)")

    # 3) Deterministic RCA results
    try:
        rca = _get(f"{base}/api/v1/rca/results/{anomaly_id}")
    except Exception as e:
        print("[3] GET /api/v1/rca/results FAILED:", e)
        return 1
    fp = _top_rca_fingerprint(rca)
    print("[3] GET /api/v1/rca/results top fingerprint:", fp)

    # 4) Explanation API (GraphRAG + validate_or_repair; uses Ollama when provider=ollama)
    try:
        expl = _get(f"{base}/api/v1/rca/explanation/{anomaly_id}", timeout=120.0)
    except Exception as e:
        print("[4] GET /api/v1/rca/explanation FAILED:", e)
        return 1
    print("[4] GET /api/v1/rca/explanation -> summary prefix:", (expl.get("explanation_summary") or "")[:120])
    prim = expl.get("primary_candidate") or {}
    print("    primary file_id:", prim.get("file_id"), "path:", prim.get("path"))

    cands = rca.get("candidates") or []
    print(f"    RCA candidates: {len(cands)}")
    if cands:
        top = cands[0]
        print("    top file_id:", top.get("file_id"), "path:", top.get("path"), "confidence:", top.get("confidence"))

    if cands and prim.get("file_id"):
        if str(cands[0].get("file_id")) != str(prim.get("file_id")):
            print("    WARNING: explanation primary_candidate.file_id differs from first RCA result row.")
        else:
            print("    OK: explanation primary matches top RCA candidate file_id.")

    print()
    print("Done. Interpretation:")
    print("  - Deterministic RCA: see [3] fingerprint (authoritative ranking).")
    print("  - Explanation API uses GraphRAG (Ollama when GRAPHRAG provider is ollama).")
    print("  - Fallback: unset OLLAMA_HOST or GRAPHRAG_LLM_PROVIDER=stub; stop Ollama to verify safe text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
