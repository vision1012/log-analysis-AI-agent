#!/usr/bin/env python3
"""Audit MCP Connection Center workspace-scoped integration behavior."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv

load_dotenv(_REPO / ".env")

WORKSPACE_ID = (os.environ.get("AUDIT_WORKSPACE_ID") or "ELM").strip()

ENV_FORBIDDEN = (
    "JIRA_API_TOKEN",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "GITHUB_ORG",
    "GITHUB_API_TOKEN",
)


def _db_enabled_rows() -> list[dict]:
    from sqlalchemy import create_engine, text

    url = os.environ.get("POSTGRES_URL", "").strip()
    if not url:
        return []
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id::text, workspace_id, provider, display_name, is_enabled
                FROM integration_connections
                WHERE workspace_id = :ws AND is_enabled = true
                ORDER BY provider
                """
            ),
            {"ws": WORKSPACE_ID},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _run_service_audit() -> dict:
    import mcp.connection_manager as cm
    import mcp.integration_resolver as ir
    from mcp.connection_manager import clear_connection_cache, validate_all_connections
    from mcp.orchestrator import MCPOrchestrator

    clear_connection_cache()

    resolver_calls: list[tuple] = []
    runtime_row_calls: list[tuple] = []
    env_hits: list[str] = []
    real_getenv = os.environ.get
    orig_resolver = ir.resolve_runtime_connection_for_workspace
    orig_runtime_from_row = ir.runtime_connection_from_row

    def _trace_resolver(ws: str, provider: str, **kwargs):
        resolver_calls.append((ws, provider, kwargs))
        return orig_resolver(ws, provider, **kwargs)

    def _trace_runtime_from_row(row: object, *, provider: str):
        runtime_row_calls.append((provider, str(getattr(row, "id", ""))))
        return orig_runtime_from_row(row, provider=provider)

    def _tracking_getenv(key: str, default=None):
        if key in ENV_FORBIDDEN:
            env_hits.append(key)
        return real_getenv(key, default)

    with (
        patch.object(ir, "resolve_runtime_connection_for_workspace", _trace_resolver),
        patch.object(cm, "runtime_connection_from_row", _trace_runtime_from_row),
        patch("os.environ.get", side_effect=_tracking_getenv),
    ):
        connections = validate_all_connections(workspace_id=WORKSPACE_ID, force_refresh=True)
        refreshed = validate_all_connections(workspace_id=WORKSPACE_ID, force_refresh=True)
        orchestrator = MCPOrchestrator()
        providers = orchestrator.health_status(workspace_id=WORKSPACE_ID)

    return {
        "workspace_id": WORKSPACE_ID,
        "list_connections": {
            "status_code": 200,
            "body": {"connections": [c.model_dump() for c in connections]},
        },
        "validate_all": {
            "status_code": 200,
            "body": {"connections": [c.model_dump() for c in refreshed]},
        },
        "status": {
            "status_code": 200,
            "body": {
                "mcp_enabled": True,
                "providers": [p.model_dump() for p in providers],
            },
        },
        "resolver_calls": [
            {"workspace_id": ws, "provider": prov, "kwargs": kw}
            for ws, prov, kw in resolver_calls
        ],
        "runtime_connection_from_row_calls": [
            {"provider": prov, "connection_id": cid} for prov, cid in runtime_row_calls
        ],
        "forbidden_env_reads": sorted(set(env_hits)),
    }


def _openapi_validate_all_registered() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return "/api/v1/mcp/connections/validate-all" in data.get("paths", {})
    except Exception:
        return False


def _curl_status_no_auth(path: str, method: str = "GET") -> int:
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception as exc:
        if hasattr(exc, "code"):
            return int(exc.code)
        return 0


def _checks(audit: dict, db_rows: list[dict], openapi_ok: bool, curl_validate_all_code: int) -> list[dict]:
    connections = audit["list_connections"]["body"]["connections"]
    db_ids = {r["id"] for r in db_rows}
    resp_ids = {c.get("connection_id") for c in connections if c.get("connection_id")}
    providers = {c.get("provider") for c in connections}
    env_reads = audit.get("forbidden_env_reads", [])

    jira = next((c for c in connections if c.get("provider") == "jira"), None)
    github = next((c for c in connections if c.get("provider") == "github"), None)

    status_providers = audit["status"]["body"].get("providers", [])
    jira_status = next((p for p in status_providers if p.get("source") == "jira"), None)
    github_status = next((p for p in status_providers if p.get("source") == "github"), None)

    resolver_ok = bool(audit.get("resolver_calls")) or bool(
        audit.get("runtime_connection_from_row_calls")
    )

    return [
        {
            "id": 1,
            "name": "GET /mcp/connections returns only enabled ELM integration rows",
            "pass": len(connections) == len(db_rows)
            and resp_ids == db_ids
            and providers == {r["provider"] for r in db_rows},
            "detail": {
                "db_enabled_count": len(db_rows),
                "response_count": len(connections),
                "db_ids": sorted(db_ids),
                "response_connection_ids": sorted(resp_ids),
            },
        },
        {
            "id": 2,
            "name": "POST /mcp/connections/validate-all registered and not 404",
            "pass": openapi_ok and curl_validate_all_code in {401, 403, 200},
            "detail": {
                "openapi_registered": openapi_ok,
                "curl_without_auth_status": curl_validate_all_code,
                "service_validate_all_status": audit["validate_all"]["status_code"],
            },
        },
        {
            "id": 3,
            "name": "Jira validation does not read JIRA_* env vars",
            "pass": jira is not None and not any(k.startswith("JIRA_") for k in env_reads),
            "detail": {"jira_health": jira, "env_reads": env_reads},
        },
        {
            "id": 4,
            "name": "GitHub validation does not read GITHUB_* env vars",
            "pass": github is not None and not any(k.startswith("GITHUB_") for k in env_reads),
            "detail": {"github_health": github, "env_reads": env_reads},
        },
        {
            "id": 5,
            "name": "DB runtime resolution used during validation",
            "pass": resolver_ok,
            "detail": {
                "resolve_runtime_connection_for_workspace_calls": audit.get("resolver_calls", []),
                "runtime_connection_from_row_calls": audit.get(
                    "runtime_connection_from_row_calls", []
                ),
            },
        },
        {
            "id": 6,
            "name": "Provider health payloads returned for Jira and GitHub",
            "pass": bool(jira and github),
            "detail": {"jira": jira, "github": github},
        },
        {
            "id": 7,
            "name": "MCP status uses DB credentials when workspace_id supplied",
            "pass": jira_status is not None
            and github_status is not None
            and not any(k.startswith(("JIRA_", "GITHUB_")) for k in env_reads),
            "detail": {
                "jira_status": jira_status,
                "github_status": github_status,
                "env_reads": env_reads,
            },
        },
    ]


def main() -> int:
    db_rows = _db_enabled_rows()
    print(f"=== MCP Connection Center audit (workspace={WORKSPACE_ID!r}) ===\n")
    print("Files executed:")
    print("  - scripts/audit_mcp_connection_center.py")
    print("  - mcp/connection_manager.py (via validate_all_connections)")
    print("  - mcp/orchestrator.py (via health_status)")
    print("  - mcp/integration_resolver.py (runtime_connection_from_row / resolver)")

    print(f"\nDB enabled integration_connections: {len(db_rows)}")
    for row in db_rows:
        print(f"  - {row['provider']}: {row['display_name']} ({row['id']})")

    audit = _run_service_audit()
    openapi_ok = _openapi_validate_all_registered()
    curl_list_code = _curl_status_no_auth(
        f"/api/v1/mcp/connections?workspace_id={WORKSPACE_ID}"
    )
    curl_validate_all_code = _curl_status_no_auth(
        f"/api/v1/mcp/connections/validate-all?workspace_id={WORKSPACE_ID}",
        method="POST",
    )
    curl_status_code = _curl_status_no_auth(
        f"/api/v1/mcp/status?workspace_id={WORKSPACE_ID}"
    )

    print("\n--- Routes tested ---")
    print(f"OpenAPI registry: GET/POST /api/v1/mcp/connections*, validate-all present={openapi_ok}")
    print(f"curl GET  /api/v1/mcp/connections?workspace_id={WORKSPACE_ID} -> HTTP {curl_list_code}")
    print(
        f"curl POST /api/v1/mcp/connections/validate-all?workspace_id={WORKSPACE_ID} -> HTTP {curl_validate_all_code}"
    )
    print(f"curl GET  /api/v1/mcp/status?workspace_id={WORKSPACE_ID} -> HTTP {curl_status_code}")
    print("service validate_all_connections(workspace_id=ELM, force_refresh=True) -> HTTP 200 equivalent")

    print("\n--- Curl commands (with Bearer token) ---")
    print(
        f'curl -s -H "Authorization: Bearer $TOKEN" '
        f'"http://127.0.0.1:8000/api/v1/mcp/connections?workspace_id={WORKSPACE_ID}"'
    )
    print(
        f'curl -s -X POST -H "Authorization: Bearer $TOKEN" '
        f'"http://127.0.0.1:8000/api/v1/mcp/connections/validate-all?workspace_id={WORKSPACE_ID}"'
    )
    print(
        f'curl -s -H "Authorization: Bearer $TOKEN" '
        f'"http://127.0.0.1:8000/api/v1/mcp/status?workspace_id={WORKSPACE_ID}"'
    )

    print("\n--- Response payloads (service-level, same schema as API) ---")
    print(json.dumps(audit["list_connections"]["body"], indent=2, default=str))
    print(json.dumps(audit["validate_all"]["body"], indent=2, default=str))
    print(json.dumps(audit["status"]["body"], indent=2, default=str))

    checks = _checks(audit, db_rows, openapi_ok, curl_validate_all_code)
    print("\n--- Pass / fail ---")
    failed = 0
    for chk in checks:
        mark = "PASS" if chk["pass"] else "FAIL"
        if not chk["pass"]:
            failed += 1
        print(f"[{mark}] {chk['id']}. {chk['name']}")
        print(json.dumps(chk["detail"], indent=2, default=str))

    print(f"\nResult: {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
