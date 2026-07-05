#!/usr/bin/env python3
"""Validate Phase 2 MCP context utilization in RCA for workspace ELM."""

from __future__ import annotations

import json
import os
import sys
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
PROJECT_KEY = (os.environ.get("AUDIT_PROJECT_KEY") or "LOGIQ").strip()
TICKET_KEY = (os.environ.get("AUDIT_TICKET_KEY") or "").strip()

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
2026-06-24T10:00:01Z ERROR auth-service request failed: connection timeout after 30s
2026-06-24T10:00:02Z ERROR auth-service Traceback (most recent call last):
  File "/Users/jay027/Desktop/github_repo/LogIQ_debug_agent_UI/src/api/http/parseIntegrationsApi.ts", line 142, in serializeCreateIntegrationBody
    raise ValueError("credentials required")
ValueError: credentials required
2026-06-24T10:00:03Z ERROR auth-service repeated timeout contacting identity provider
"""


def _discover_ticket_key() -> tuple[str, Any | None]:
    if TICKET_KEY:
        return TICKET_KEY, None
    from api.services.jira_service import search_tickets

    jql = f"project = {PROJECT_KEY} ORDER BY updated DESC"
    try:
        hits = search_tickets(jql=jql, max_results=1, workspace_id=WORKSPACE_ID)
        if hits.issues:
            return hits.issues[0].ticket_key, None
    except Exception as exc:
        print(f"ticket discovery via JQL failed: {exc}")
    return f"{PROJECT_KEY}-1", None


def _ticket_from_mcp(ctx: Any) -> Any:
    from schemas.jira import JiraNormalizedTicket

    t = ctx.ticket_context
    return JiraNormalizedTicket(
        ticket_id=t.issue_key,
        ticket_key=t.issue_key,
        summary=t.summary or "",
        description=t.description or "",
        comments_text="",
        status=t.status or "unknown",
        priority=t.priority or "unknown",
        labels=list(t.labels or []),
        created_at="",
        updated_at="",
        url=t.url or "",
        cleaned_text_body=(t.summary or "") + " " + (t.description or ""),
    )


def _trace_env_reads(fn):
    hits: list[str] = []
    real_get = os.environ.get

    def tracking_get(name: str, default=None):
        if name in ENV_FORBIDDEN:
            hits.append(name)
        return real_get(name, default)

    with patch("os.environ.get", side_effect=tracking_get):
        result = fn()
    return result, sorted(set(hits))


def _fetch_mcp(ticket_key: str) -> tuple[Any, list[str]]:
    from mcp.config import MCPFetchParams
    from mcp.orchestrator import MCPOrchestrator

    def _run():
        params = MCPFetchParams(
            ticket_key=ticket_key,
            service_name="auth-service",
            repo_name=REPO_NAME,
            workspace_id=WORKSPACE_ID,
            enabled_sources=["jira", "github"],
        )
        return MCPOrchestrator().fetch_context(params)

    return _trace_env_reads(_run)


def _run_rca(ticket_key: str, embedded_ticket: Any | None = None) -> tuple[Any, list[str]]:
    from api.services.jira_rca_orchestration_service import run_jira_rca
    from schemas.jira_rca import JiraRcaRunRequest

    body = JiraRcaRunRequest(
        ticket_key=ticket_key,
        ticket=embedded_ticket,
        log_content=SAMPLE_LOG,
        workspace_id=WORKSPACE_ID,
        repo_name=REPO_NAME,
        idempotency_key=f"phase2-validate-{ticket_key}",
    )

    def _run():
        return run_jira_rca(body)

    return _trace_env_reads(_run)


def _neo4j_report(investigation_id: str) -> dict[str, Any]:
    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient.from_env()
    client.connect()
    try:
        inv = client.execute_read(
            "MATCH (i:Investigation {id: $id}) RETURN i.id AS id, i.ticket_key AS ticket_key",
            {"id": investigation_id},
        )
        ticket = client.execute_read(
            """
            MATCH (i:Investigation {id: $id})-[:REFERENCES_TICKET]->(t:JiraTicket)
            RETURN t.issue_key AS key, t.status AS status, t.labels AS labels, t.comments_count AS comments_count
            """,
            {"id": investigation_id},
        )
        commits = client.execute_read(
            """
            MATCH (i:Investigation {id: $id})-[:INVESTIGATED_COMMIT]->(c:Commit)
            RETURN count(c) AS n, collect(c.sha)[0..3] AS sample_shas, collect(c.changed_files)[0] AS sample_files
            """,
            {"id": investigation_id},
        )
        prs = client.execute_read(
            """
            MATCH (i:Investigation {id: $id})-[:INVESTIGATED_PR]->(p:PullRequest)
            RETURN count(p) AS n, collect(p.number)[0..3] AS sample_numbers, collect(p.changed_files)[0] AS sample_files
            """,
            {"id": investigation_id},
        )
        rels = client.execute_read(
            """
            MATCH (i:Investigation {id: $id})-[r]->()
            RETURN type(r) AS rel, count(*) AS c ORDER BY rel
            """,
            {"id": investigation_id},
        )
        return {
            "investigation": inv[0] if inv else None,
            "jira_ticket": ticket[0] if ticket else None,
            "commits": commits[0] if commits else None,
            "pull_requests": prs[0] if prs else None,
            "outgoing_relationships": rels,
        }
    finally:
        client.close()


def _read_evidence_bundle(bundle_id: str) -> dict[str, Any]:
    import tempfile
    from artifacts.evidence_store import LocalFileEvidenceStore

    base = os.environ.get("EVIDENCE_STORE_DIR") or tempfile.gettempdir()
    store = LocalFileEvidenceStore(Path(base) / "evidence_bundles")
    data = store.get_bundle(bundle_id) or {}
    return {k: data.get(k) for k in data if k != "credentials"}



def _log_github_match_diagnostics(mcp_ctx: Any, candidate_path: str) -> None:
    from rca_engine.mcp_context_signals import (
        _path_matches_changed_files,
        _pr_changed_files,
        compute_mcp_context_signals_for_path,
        normalize_candidate_path,
    )

    normalized = normalize_candidate_path(candidate_path)
    print("\n--- GitHub PR match diagnostics ---")
    print(f"candidate_path={candidate_path}")
    print(f"candidate_path_normalized={normalized}")
    print(f"fetched_pr_count={len(mcp_ctx.pull_requests)}")
    total_changed_files = sum(len(_pr_changed_files(pr)) for pr in mcp_ctx.pull_requests[:20])
    print(f"pr_changed_files_total={total_changed_files}")
    for pr in mcp_ctx.pull_requests[:5]:
        changed = _pr_changed_files(pr)
        matched = [cf for cf in changed if _path_matches_changed_files(normalized or candidate_path, [cf])]
        print(
            f"  pr #{pr.number} changed_files={len(changed)} "
            f"matched_files={matched[:5]} title={(pr.title or '')[:80]}"
        )
    _, refs = compute_mcp_context_signals_for_path(candidate_path, mcp_ctx)
    print(f"matched_pr_files={refs.get('matched_changed_files') or []}")
    print(f"matched_pull_requests={refs.get('matched_pull_requests') or []}")


def main() -> int:
    print("=== Phase 2 MCP RCA Validation (ELM) ===")
    print(f"workspace={WORKSPACE_ID} repo={REPO_NAME} project={PROJECT_KEY}")
    print()

    ticket_key, discovered_ctx = _discover_ticket_key()
    print(f"ticket_key={ticket_key}")

    mcp_ctx, env_mcp = _fetch_mcp(ticket_key)
    embedded = None
    if mcp_ctx.ticket_context:
        embedded = _ticket_from_mcp(mcp_ctx)
    elif discovered_ctx and discovered_ctx.ticket_context:
        embedded = _ticket_from_mcp(discovered_ctx)
    elif not mcp_ctx.ticket_context:
        from schemas.jira import JiraNormalizedTicket

        print("WARNING: no Jira issues in workspace; using synthetic ticket for jira_log RCA path")
        embedded = JiraNormalizedTicket(
            ticket_id=ticket_key,
            ticket_key=ticket_key,
            summary="Phase 2 validation (synthetic — no Jira issues in LOGIQ project)",
            description=SAMPLE_LOG[:500],
            comments_text="",
            status="Open",
            priority="Medium",
            labels=["phase2-validation"],
            created_at="",
            updated_at="",
            url="",
            cleaned_text_body="parseIntegrationsApi credentials required auth-service timeout",
        )
    print(f"MCP fetch: commits={len(mcp_ctx.commits)} prs={len(mcp_ctx.pull_requests)} "
          f"jira={bool(mcp_ctx.ticket_context)} env_reads={env_mcp}")
    for meta in mcp_ctx.source_metadata:
        if getattr(meta, "source", "") == "github":
            print(f"github_metadata_detail={getattr(meta, 'detail', '')}")

    resp, env_rca = _run_rca(ticket_key, embedded_ticket=embedded)
    env_reads = sorted(set(env_mcp + env_rca))
    investigation_id = str(resp.rca.evidence_summary.get("investigation_id") or "")
    candidates = resp.rca.rca_result.get("candidate_root_causes") or []
    top = candidates[0] if candidates else {}
    signals = top.get("signal_scores") or {}
    mcp_signal_keys = [
        "recent_commit_match",
        "recent_pr_match",
        "changed_file_match",
        "jira_ticket_match",
        "jira_label_match",
        "author_activity_match",
    ]
    prefixed = {k: signals.get(f"mcp_{k}", signals.get(k, 0)) for k in mcp_signal_keys}
    candidate_path = str(top.get("path") or "")
    if candidate_path:
        _log_github_match_diagnostics(mcp_ctx, candidate_path)

    evidence_refs = resp.rca.evidence_summary.get("evidence_refs") or []
    bundle_excerpt: dict[str, Any] = {}
    if evidence_refs:
        bundle_excerpt = _read_evidence_bundle(str(evidence_refs[0]))

    neo4j = _neo4j_report(investigation_id) if investigation_id else {}

    checks = [
        ("Jira provider fetches real ticket context", bool(mcp_ctx.ticket_context and mcp_ctx.ticket_context.issue_key)),
        ("GitHub provider fetches commits/PRs", len(mcp_ctx.commits) > 0 or len(mcp_ctx.pull_requests) > 0),
        ("GitHub changed_files present", any(getattr(c, "changed_files", None) for c in mcp_ctx.commits[:5]) or any(getattr(p, "changed_files", None) for p in mcp_ctx.pull_requests[:5])),
        ("jira_log mode used", resp.rca.rca_result.get("mode") == "jira_log"),
        ("MCP signals in ranking", any(float(prefixed.get(k) or 0) > 0 for k in mcp_signal_keys)),
        ("recent_commit_match > 0", float(prefixed.get("recent_commit_match") or 0) > 0),
        ("changed_file_match > 0", float(prefixed.get("changed_file_match") or 0) > 0),
        ("Evidence bundle MCP refs", bool(
            bundle_excerpt.get("matched_commits")
            or bundle_excerpt.get("matched_pull_requests")
            or bundle_excerpt.get("jira_ticket_key")
        )),
        ("Neo4j Investigation node", bool(neo4j.get("investigation"))),
        ("Neo4j JiraTicket + REFERENCES_TICKET", bool(neo4j.get("jira_ticket"))),
        ("Neo4j Commit nodes + INVESTIGATED_COMMIT", int((neo4j.get("commits") or {}).get("n") or 0) > 0),
        ("Neo4j PullRequest nodes + INVESTIGATED_PR", int((neo4j.get("pull_requests") or {}).get("n") or 0) > 0),
        ("Explanation cites MCP", "MCP context supports" in (resp.explanation_payload.explanation or "")),
        ("No forbidden env reads", len(env_reads) == 0),
    ]

    print("\n--- Pass/Fail ---")
    failed = 0
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {name}")

    print("\n--- MCP signals (top candidate) ---")
    print(json.dumps(prefixed, indent=2))

    print("\n--- Sample response (truncated) ---")
    sample = {
        "ticket_key": ticket_key,
        "run_status": resp.rca.run_status,
        "mode": resp.rca.rca_result.get("mode"),
        "investigation_id": investigation_id,
        "top_candidate": {
            "path": top.get("path"),
            "confidence": top.get("confidence"),
            "mcp_artifact_refs": top.get("mcp_artifact_refs"),
            "signal_scores": {k: signals[k] for k in signals if str(k).startswith("mcp_") or k in mcp_signal_keys},
        },
        "evidence_summary": resp.rca.evidence_summary,
        "mcp_context_summary": resp.explanation_payload.mcp_context_summary,
    }
    print(json.dumps(sample, indent=2, default=str)[:4000])

    print("\n--- Neo4j query results ---")
    print(json.dumps(neo4j, indent=2, default=str))

    print("\n--- Evidence bundle excerpt ---")
    print(json.dumps(bundle_excerpt, indent=2, default=str)[:2500])

    print("\n--- Explanation excerpt ---")
    print(resp.explanation_payload.explanation[:1200])

    print(f"\nSummary: {len(checks)-failed}/{len(checks)} passed; env_reads={env_reads}")
    blockers = [name for name, ok in checks if not ok]
    if blockers:
        print("Blockers:", "; ".join(blockers))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
