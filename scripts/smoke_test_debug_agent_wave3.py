#!/usr/bin/env python3
"""
Smoke test for debug_agent Wave 3 full pipeline.

Steps:
1) create or reuse a sample anomaly
2) run full 7-agent pipeline
3) print key investigation fields
4) validate structured output + fallback behavior

Usage:
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=xxx \
      python scripts/smoke_test_debug_agent_wave3.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _require_password() -> str:
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    return password


def _has_candidates(client, anomaly_id: str) -> bool:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(:File)
    WHERE r.status IN ['candidate', 'accepted']
    RETURN count(r) AS n
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return bool(rows and int(rows[0].get("n", 0) or 0) > 0)


def _latest_run_id(client, anomaly_id: str) -> str:
    q = """
    MATCH (:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->(:File)
    WHERE r.status IN ['candidate', 'accepted']
    RETURN r.run_id AS run_id, coalesce(r.created_at, '') AS ts
    ORDER BY ts DESC
    LIMIT 1
    """
    rows = client.execute_read(q, {"anomaly_id": anomaly_id})
    return (rows[0].get("run_id") if rows else "") or ""


def _create_test_anomaly(client, writer, anomaly_id: str) -> None:
    """Create minimal graph state required by deterministic RCA."""
    trace_ref = "smoke-debug-wave3-trace"
    repo_ref = "smoke-debug-wave3-repo"
    service_ref = "smoke-debug-wave3-service"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="smoke-debug-wave3-window")
    client.execute_write(
        "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
        {"id": anomaly_id, "service_ref": service_ref},
    )
    client.execute_write(
        """
        MATCH (a:Anomaly {id: $id})
        SET a.title = $title, a.message = $message, a.severity = $severity, a.score = $score
        """,
        {
            "id": anomaly_id,
            "title": "Timeout in API handler",
            "message": "Request timed out while waiting for downstream response",
            "severity": "high",
            "score": 0.86,
        },
    )

    writer.upsert_stackframe("dbg3-f0", trace_ref, symbol_name="main", frame_order=0, resolution="resolved")
    writer.upsert_stackframe("dbg3-f1", trace_ref, symbol_name="handler", frame_order=1, resolution="resolved")
    writer.upsert_stackframe("dbg3-f2", trace_ref, symbol_name="process", frame_order=2, resolution="resolved")

    writer.link_has_frame(anomaly_id, "dbg3-f0", 0)
    writer.link_has_frame(anomaly_id, "dbg3-f1", 1)
    writer.link_has_frame(anomaly_id, "dbg3-f2", 2)

    writer.upsert_file("src/debug_wave3/foo.py", repo_ref)
    writer.upsert_file("src/debug_wave3/bar.py", repo_ref)

    from graph.writer import _compute_file_id
    foo_id = _compute_file_id(repo_ref, "src/debug_wave3/foo.py")
    bar_id = _compute_file_id(repo_ref, "src/debug_wave3/bar.py")
    writer.link_in_file("dbg3-f0", foo_id)
    writer.link_in_file("dbg3-f1", foo_id)
    writer.link_in_file("dbg3-f2", bar_id)

    commit_sha = "debugwave3abc123"
    deploy_id = "debug-wave3-deploy-001"
    writer.upsert_commit(commit_sha, repo_ref, ts)
    writer.upsert_deployment(deploy_id, ts, service_ref=service_ref)
    writer.link_touched(commit_sha, repo_ref, foo_id)
    writer.link_touched(commit_sha, repo_ref, bar_id)
    writer.link_deployed_commit(deploy_id, commit_sha, repo_ref)


def _ensure_candidates(client, anomaly_id: str) -> str:
    """Create/reuse anomaly and ensure deterministic RCA candidates exist."""
    if _has_candidates(client, anomaly_id):
        return _latest_run_id(client, anomaly_id)

    from api.services.rca_service import run_rca
    from artifacts.evidence_store import LocalFileEvidenceStore
    from graph.writer import GraphWriter

    writer = GraphWriter(client)
    _create_test_anomaly(client, writer, anomaly_id)

    evidence_base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    store = LocalFileEvidenceStore(os.path.join(evidence_base, "evidence_bundles"))
    run_id = f"smoke-debug-wave3-{uuid.uuid4().hex[:8]}"
    result = run_rca(
        anomaly_id,
        trigger_type="manual",
        run_id=run_id,
        override=True,
        graph_client=client,
        graph_writer=writer,
        evidence_store=store,
    )
    if result is None:
        raise RuntimeError("Deterministic RCA did not produce candidates for smoke anomaly.")
    return str(result.get("run_id") or run_id)


def _validate_result_shape(result: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return False, ["result is not an object"]

    for key in ("anomaly_id", "run_id", "status", "investigation_report", "steps"):
        if key not in result:
            errors.append(f"missing key: {key}")

    steps = result.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be a list")
        steps = []
    else:
        kinds = [s.get("kind") for s in steps if isinstance(s, dict)]
        required_kinds = {"triage", "rca", "evidence", "memory", "explanation", "remediation", "reporting"}
        missing = sorted(required_kinds.difference(set(kinds)))
        if missing:
            errors.append(f"missing pipeline steps: {', '.join(missing)}")

    report = result.get("investigation_report")
    if not isinstance(report, dict):
        errors.append("investigation_report must be an object")
        return len(errors) == 0, errors

    required_report_keys = (
        "triage_summary",
        "root_cause_candidates",
        "primary_candidate",
        "evidence_highlights",
        "similar_incidents",
        "explanation_summary",
        "remediation_steps",
        "final_report_summary",
    )
    for k in required_report_keys:
        if k not in report:
            errors.append(f"missing investigation_report key: {k}")

    # Fallback checks: explanation/remediation may fail but report should remain populated.
    if isinstance(steps, list):
        for kind, field in [("explanation", "explanation_summary"), ("remediation", "remediation_steps")]:
            matches = [s for s in steps if isinstance(s, dict) and s.get("kind") == kind]
            if matches and not bool(matches[0].get("success")):
                if field == "remediation_steps":
                    if not isinstance(report.get(field), list):
                        errors.append(f"{kind} failed but {field} missing/non-list in report")
                else:
                    if not report.get(field):
                        errors.append(f"{kind} failed but {field} missing in report")

    return len(errors) == 0, errors


def _step_output(result: dict[str, Any], kind: str) -> dict[str, Any]:
    for step in (result.get("steps") or []):
        if isinstance(step, dict) and step.get("kind") == kind:
            out = step.get("output")
            return out if isinstance(out, dict) else {}
    return {}


def _extract_severity(result: dict[str, Any], report: dict[str, Any]) -> str:
    triage = _step_output(result, "triage")
    if isinstance(triage, dict):
        sev = str(triage.get("severity") or triage.get("priority") or "")
        if sev:
            return sev
    triage_summary = str(report.get("triage_summary") or "")
    parts = triage_summary.split("severity=")
    if len(parts) > 1:
        return parts[1].split(",")[0].strip() or "unknown"
    return "unknown"


def _print_report(result: dict[str, Any]) -> None:
    report = result.get("investigation_report") or {}
    if not isinstance(report, dict):
        report = {}

    primary = report.get("primary_candidate") or {}
    if not isinstance(primary, dict):
        primary = {}

    print("\n=== Debug Agent Wave 3 Investigation ===")
    print(f"anomaly_id: {result.get('anomaly_id')}")
    print(f"triage summary: {report.get('triage_summary')}")
    print(f"severity: {_extract_severity(result, report)}")
    print(f"primary RCA candidate: {primary.get('path') or primary.get('file_id')}")
    print("evidence highlights:")
    for item in (report.get("evidence_highlights") or []):
        print(f" - {item}")
    print(f"similar incidents: {len(report.get('similar_incidents') or [])}")
    print(f"explanation summary: {report.get('explanation_summary')}")
    print("remediation steps:")
    for step in (report.get("remediation_steps") or []):
        print(f" - {step}")
    print(f"final report summary: {report.get('final_report_summary')}")


def _set_env_var(key: str, value: Optional[str]) -> None:
    if value is None:
        if key in os.environ:
            del os.environ[key]
    else:
        os.environ[key] = value


def _verify_fallback_when_llm_unavailable(anomaly_id: str, run_id: str) -> tuple[bool, list[str]]:
    """
    Force LLM-unavailable mode and verify pipeline still returns structured output.

    We intentionally use an unsupported provider to trigger safe fallback paths.
    """
    from debug_agent.orchestrator import run_debug_session

    errors: list[str] = []
    env_keys = [
        "DEBUG_AGENT_EXPLANATION_USE_LLM",
        "DEBUG_AGENT_REMEDIATION_USE_LLM",
        "DEBUG_AGENT_REPORTING_USE_LLM",
        "GRAPHRAG_LLM_PROVIDER",
    ]
    prev = {k: os.environ.get(k) for k in env_keys}
    try:
        _set_env_var("DEBUG_AGENT_EXPLANATION_USE_LLM", "true")
        _set_env_var("DEBUG_AGENT_REMEDIATION_USE_LLM", "true")
        _set_env_var("DEBUG_AGENT_REPORTING_USE_LLM", "true")
        _set_env_var("GRAPHRAG_LLM_PROVIDER", "unsupported_provider")

        result = run_debug_session(anomaly_id, run_id=run_id or None)
        ok, shape_errors = _validate_result_shape(result)
        if not ok:
            errors.extend([f"fallback shape invalid: {e}" for e in shape_errors])
            return False, errors

        remediation_output = _step_output(result, "remediation")
        remediation_meta = remediation_output.get("metadata") if isinstance(remediation_output, dict) else {}
        remediation_source = remediation_meta.get("source") if isinstance(remediation_meta, dict) else None
        reporting_output = _step_output(result, "reporting")
        reporting_meta = reporting_output.get("metadata") if isinstance(reporting_output, dict) else {}
        reporting_source = reporting_meta.get("source") if isinstance(reporting_meta, dict) else None

        fallback_signals = {
            "remediation_deterministic_fallback": remediation_source == "deterministic_fallback",
            "reporting_deterministic": reporting_source == "deterministic",
        }
        if not any(fallback_signals.values()):
            errors.append("no fallback signal detected when LLM provider unavailable")
        return len(errors) == 0, errors
    except Exception as exc:
        return False, [f"fallback run crashed: {exc}"]
    finally:
        for k, v in prev.items():
            _set_env_var(k, v)


def main() -> None:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = _require_password()
    anomaly_id = os.environ.get("SMOKE_DEBUG_AGENT_WAVE3_ANOMALY_ID", "smoke-debug-agent-wave3-001")

    from debug_agent.orchestrator import run_debug_session
    from graph.migrations import apply_migrations
    from graph.neo4j_client import Neo4jClient

    apply_migrations(uri, user, password)
    client = Neo4jClient(uri, user, password)
    client.connect()

    try:
        run_id = _ensure_candidates(client, anomaly_id)
        print(f"[ready] anomaly={anomaly_id} run_id={run_id or 'latest'}")

        result = run_debug_session(anomaly_id, run_id=run_id or None)
        _print_report(result)

        ok, errors = _validate_result_shape(result)
        print(f"\nstructured result valid: {ok}")
        if not ok:
            print("validation errors:")
            for e in errors:
                print(f" - {e}")
            sys.exit(2)

        fallback_ok, fallback_errors = _verify_fallback_when_llm_unavailable(anomaly_id, run_id)
        print(f"fallback valid when LLM unavailable: {fallback_ok}")
        if not fallback_ok:
            print("fallback verification errors:")
            for e in fallback_errors:
                print(f" - {e}")
            sys.exit(3)

        print("\nDEBUG_AGENT_WAVE3_COMPLETE")
    finally:
        client.close()


if __name__ == "__main__":
    main()

