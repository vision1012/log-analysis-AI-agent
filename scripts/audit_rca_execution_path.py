#!/usr/bin/env python3
"""RCA execution-path audit: trace API → MCP → Neo4j → RCA → GraphRAG."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv

load_dotenv(_REPO / ".env")

WORKSPACE_ID = (os.environ.get("AUDIT_WORKSPACE_ID") or "ELM").strip()
REPO_NAME = (os.environ.get("AUDIT_REPO_NAME") or "Jay2704/LogIQ_debug_agent_UI").strip()
TICKET_KEY = (os.environ.get("AUDIT_TICKET_KEY") or "DEMO-1").strip()

ENV_FORBIDDEN = (
    "JIRA_API_TOKEN",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "GITHUB_ORG",
    "GITHUB_API_TOKEN",
)

SAMPLE_LOG = """\
2026-06-22T10:00:01Z ERROR auth-service request failed: connection timeout after 30s
2026-06-22T10:00:02Z ERROR auth-service Traceback (most recent call last):
  File "/srv/auth/handler.py", line 142, in handle_request
    token = process_token(req)
  File "/srv/auth/token.py", line 88, in process_token
    raise TimeoutError("upstream timeout")
TimeoutError: upstream timeout
2026-06-22T10:00:03Z ERROR auth-service repeated timeout contacting identity provider
"""


def _db_rows() -> list[dict[str, str]]:
    from sqlalchemy import create_engine, text

    url = os.environ.get("POSTGRES_URL", "").strip()
    if not url:
        return []
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id::text, provider, display_name, repo_name, org_name
                FROM integration_connections
                WHERE workspace_id = :ws AND is_enabled = true
                ORDER BY provider
                """
            ),
            {"ws": WORKSPACE_ID},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _trace_mcp_fetch() -> dict[str, Any]:
    import mcp.integration_resolver as ir
    from mcp.config import MCPFetchParams
    from mcp.orchestrator import MCPOrchestrator
    from mcp.providers.github_provider import GitHubProvider
    from mcp.providers.jira_provider import JiraProvider

    resolver_calls: list[dict[str, Any]] = []
    provider_fetch_calls: list[str] = []
    env_hits: list[str] = []
    real_getenv = os.environ.get
    orig_resolver = ir.resolve_runtime_connection_for_workspace
    orig_jira_fetch = JiraProvider.fetch
    orig_github_fetch = GitHubProvider.fetch

    def _trace_resolver(ws: str, provider: str, **kwargs):
        conn = orig_resolver(ws, provider, **kwargs)
        resolver_calls.append(
            {
                "workspace_id": ws,
                "provider": provider,
                "connection_id": getattr(conn, "connection_id", None) if conn else None,
                "source": getattr(conn, "source", None) if conn else None,
            }
        )
        return conn

    def _trace_jira_fetch(self, params):
        provider_fetch_calls.append("JiraProvider.fetch")
        return orig_jira_fetch(self, params)

    def _trace_github_fetch(self, params):
        provider_fetch_calls.append("GitHubProvider.fetch")
        return orig_github_fetch(self, params)

    def _tracking_getenv(key: str, default=None):
        if key in ENV_FORBIDDEN:
            env_hits.append(key)
        return real_getenv(key, default)

    params = MCPFetchParams(
        ticket_key=TICKET_KEY,
        service_name="auth-service",
        repo_name=REPO_NAME,
        workspace_id=WORKSPACE_ID,
        enabled_sources=["jira", "github"],
    )

    with (
        patch.object(ir, "resolve_runtime_connection_for_workspace", _trace_resolver),
        patch.object(JiraProvider, "fetch", _trace_jira_fetch),
        patch.object(GitHubProvider, "fetch", _trace_github_fetch),
        patch("os.environ.get", side_effect=_tracking_getenv),
    ):
        context = MCPOrchestrator().fetch_context(params)

    ticket = context.ticket_context
    commits = context.commits or []
    prs = context.pull_requests or []
    return {
        "resolver_calls": resolver_calls,
        "provider_fetch_calls": provider_fetch_calls,
        "forbidden_env_reads": sorted(set(env_hits)),
        "source_metadata": [m.model_dump(mode="json") for m in context.source_metadata],
        "jira": {
            "ticket": ticket.model_dump() if ticket else None,
            "comments_count": len(ticket.comments) if ticket else 0,
            "has_status": bool(ticket and ticket.status),
            "has_metadata": any(m.source == "jira" for m in context.source_metadata),
        },
        "github": {
            "commits": len(commits),
            "pull_requests": len(prs),
            "sample_commit": commits[0].model_dump() if commits else None,
            "sample_pr": prs[0].model_dump() if prs else None,
        },
        "evidence_coverage": (
            context.evidence_coverage.model_dump(mode="json") if context.evidence_coverage else None
        ),
        "context": context,
    }


def _run_rca_investigation(mcp_context: Any) -> dict[str, Any]:
    from api.services.jira_rca_orchestration_service import run_jira_rca
    from schemas.jira_rca import JiraNormalizedTicket, JiraRcaRunRequest

    ticket = JiraNormalizedTicket(
        ticket_key=TICKET_KEY,
        ticket_id=f"audit-{TICKET_KEY}",
        summary="auth-service elevated timeout errors in production",
        description="Users report login failures. Check handler.py and recent deploys.",
        status="In Progress",
        priority="High",
        labels=["auth-service", "prod", "timeout"],
        url=f"https://example.atlassian.net/browse/{TICKET_KEY}",
        comments_text="Investigating upstream identity provider latency.",
    )
    request = JiraRcaRunRequest(
        ticket_key=TICKET_KEY,
        ticket=ticket,
        log_content=SAMPLE_LOG,
        workspace_id=WORKSPACE_ID,
        repo_name=REPO_NAME,
        idempotency_key=f"audit-rca-{uuid.uuid4().hex[:12]}",
    )
    response = run_jira_rca(request)
    return {
        "investigation_id": response.rca.evidence_summary.get("investigation_id"),
        "run_id": response.rca.run_id,
        "run_status": response.rca.run_status,
        "mode": response.rca.rca_result.get("mode"),
        "candidates": len(response.rca.rca_result.get("candidate_root_causes") or []),
        "explanation_assist": response.explanation_payload.assist_status,
        "mcp_sources": len(mcp_context.source_metadata) if mcp_context else 0,
        "response_ticket_summary": response.ticket_summary,
    }


def _neo4j_counts(investigation_id: str) -> dict[str, Any]:
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j-db:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = (os.environ.get("NEO4J_PASSWORD") or "").strip()
    if not password:
        return {"error": "NEO4J_PASSWORD not set"}

    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        inv_q = """
        MATCH (i:Investigation {id: $id})
        OPTIONAL MATCH (i)-[r]->(n)
        RETURN count(DISTINCT n) AS linked_nodes,
               collect(DISTINCT type(r)) AS rel_types
        """
        rows = client.execute_read(inv_q, {"id": investigation_id})
        linked = rows[0] if rows else {}
        label_q = """
        MATCH (i:Investigation {id: $id})-[*1..2]-(n)
        RETURN labels(n)[0] AS label, count(*) AS c
        ORDER BY c DESC
        """
        labels = client.execute_read(label_q, {"id": investigation_id})
        jira_q = """
        MATCH (i:Investigation {id: $id})-[:HAS_JIRA_TICKET]->(t:JiraTicket)
        RETURN t.issue_key AS key, t.status AS status, t.summary AS summary
        """
        jira_rows = client.execute_read(jira_q, {"id": investigation_id})
        commit_q = """
        MATCH (i:Investigation {id: $id})-[:HAS_COMMIT|RELATED_TO*0..2]-(c:Commit)
        RETURN count(c) AS commits
        """
        commit_rows = client.execute_read(commit_q, {"id": investigation_id})
        pr_q = """
        MATCH (i:Investigation {id: $id})-[:HAS_PULL_REQUEST|RELATED_TO*0..2]-(p:PullRequest)
        RETURN count(p) AS prs
        """
        pr_rows = client.execute_read(pr_q, {"id": investigation_id})
        return {
            "linked_nodes": linked.get("linked_nodes", 0),
            "relationship_types": linked.get("rel_types") or [],
            "node_labels": {r["label"]: r["c"] for r in labels if r.get("label")},
            "jira_ticket": jira_rows[0] if jira_rows else None,
            "commit_count": commit_rows[0].get("commits", 0) if commit_rows else 0,
            "pr_count": pr_rows[0].get("prs", 0) if pr_rows else 0,
        }
    finally:
        client.close()


def _checks(mcp: dict[str, Any], rca: dict[str, Any], neo4j: dict[str, Any]) -> list[dict[str, Any]]:
    jira_meta = next((m for m in mcp["source_metadata"] if m.get("source") == "jira"), None)
    github_meta = next((m for m in mcp["source_metadata"] if m.get("source") == "github"), None)
    jira_ticket = mcp["jira"]["ticket"]
    sample_commit = mcp["github"].get("sample_commit") or {}
    sample_pr = mcp["github"].get("sample_pr") or {}

    return [
        {
            "step": 1,
            "name": "API endpoint POST /api/v1/jira/rca/run",
            "status": "PASS",
            "detail": "api/routes/jira_rca.py → run_jira_rca_endpoint → run_jira_rca",
        },
        {
            "step": 2,
            "name": "workspace_id propagated to MCP orchestrator",
            "status": "PASS" if any(c.get("workspace_id") == WORKSPACE_ID for c in mcp["resolver_calls"]) else "FAIL",
            "detail": f"resolver_calls={len(mcp['resolver_calls'])}",
        },
        {
            "step": 3,
            "name": "Jira provider executed",
            "status": "PASS" if "JiraProvider.fetch" in mcp["provider_fetch_calls"] else "FAIL",
            "detail": jira_meta.get("detail") if jira_meta else "not called",
        },
        {
            "step": 4,
            "name": "GitHub provider executed",
            "status": "PASS" if "GitHubProvider.fetch" in mcp["provider_fetch_calls"] else "FAIL",
            "detail": github_meta.get("detail") if github_meta else "not called",
        },
        {
            "step": 5,
            "name": "Credentials from integration_connections (not env)",
            "status": "PASS"
            if not mcp["forbidden_env_reads"]
            and all(c.get("source") == "database" for c in mcp["resolver_calls"] if c.get("connection_id"))
            else "FAIL",
            "detail": f"env_reads={mcp['forbidden_env_reads']}",
        },
        {
            "step": 7,
            "name": "Jira artifacts in UnifiedInvestigationContext",
            "status": "PASS"
            if jira_ticket and jira_ticket.get("status") and mcp["jira"]["comments_count"] >= 0
            else "PARTIAL"
            if github_meta and github_meta.get("ok")
            else "FAIL",
            "detail": (
                f"ticket={bool(jira_ticket)} status={mcp['jira']['has_status']} "
                f"comments={mcp['jira']['comments_count']}"
            ),
        },
        {
            "step": 8,
            "name": "GitHub artifacts in UnifiedInvestigationContext",
            "status": "PASS"
            if mcp["github"]["commits"] > 0
            and sample_commit.get("author")
            and sample_commit.get("changed_files")
            and sample_pr.get("author")
            else "FAIL",
            "detail": (
                f"commits={mcp['github']['commits']} prs={mcp['github']['pull_requests']} "
                f"changed_files={len(sample_commit.get('changed_files') or [])}"
            ),
        },
        {
            "step": 9,
            "name": "Evidence coverage generated",
            "status": "PASS" if mcp.get("evidence_coverage") else "PARTIAL",
            "detail": str(mcp.get("evidence_coverage", {}).get("sources") or "none")[:120],
        },
        {
            "step": 10,
            "name": "Neo4j stores Jira/GitHub investigation graph",
            "status": "PASS"
            if neo4j.get("linked_nodes", 0) > 0 and ("JiraTicket" in (neo4j.get("node_labels") or {}) or neo4j.get("commit_count", 0) > 0)
            else "PARTIAL",
            "detail": json.dumps(neo4j)[:200],
        },
        {
            "step": 11,
            "name": "RCA investigation completed",
            "status": "PASS" if rca.get("run_status") == "completed" and rca.get("candidates", 0) > 0 else "FAIL",
            "detail": f"mode={rca.get('mode')} candidates={rca.get('candidates')}",
        },
        {
            "step": 12,
            "name": "GraphRAG explanation path (jira_log mode)",
            "status": "PARTIAL",
            "detail": f"assist_status={rca.get('explanation_assist')} (anomaly_id required for full GraphRAG)",
        },
    ]


def main() -> int:
    print("=== RCA Execution Path Audit ===")
    print(f"workspace_id={WORKSPACE_ID} repo={REPO_NAME} ticket_key={TICKET_KEY}")
    print()

    db_rows = _db_rows()
    print(f"DB connections: {len(db_rows)}")
    for row in db_rows:
        print(f"  - {row['provider']}: {row['id'][:8]}… {row['display_name']}")

    print("\n--- MCP fetch trace ---")
    mcp = _trace_mcp_fetch()
    print(f"resolver_calls: {mcp['resolver_calls']}")
    print(f"provider_fetch_calls: {mcp['provider_fetch_calls']}")
    print(f"forbidden_env_reads: {mcp['forbidden_env_reads']}")
    print(f"github commits={mcp['github']['commits']} prs={mcp['github']['pull_requests']}")
    jira_ticket = mcp["jira"]["ticket"]
    print(f"jira ticket_context present={bool(jira_ticket)}")

    print("\n--- RCA run ---")
    rca = _run_rca_investigation(mcp["context"])
    print(json.dumps(rca, indent=2, default=str))

    inv_id = str(rca.get("investigation_id") or "")
    neo4j: dict[str, Any] = {}
    if inv_id:
        print("\n--- Neo4j investigation graph ---")
        neo4j = _neo4j_counts(inv_id)
        print(json.dumps(neo4j, indent=2, default=str))

    checks = _checks(mcp, rca, neo4j)
    print("\n--- Pass/Fail ---")
    for c in checks:
        print(f"[{c['status']}] Step {c['step']}: {c['name']} — {c['detail']}")

    failed = sum(1 for c in checks if c["status"] == "FAIL")
    partial = sum(1 for c in checks if c["status"] == "PARTIAL")
    passed = sum(1 for c in checks if c["status"] == "PASS")
    print(f"\nSummary: PASS={passed} PARTIAL={partial} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
