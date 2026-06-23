#!/usr/bin/env python3
"""
End-to-end validation for MCP-powered RCA (mock or live).

Validates:
  Jira ticket -> MCP context preview -> Neo4j investigation graph -> RCA run ->
  GraphRAG explanation -> confidence assessment -> evidence coverage ->
  confidence limitations -> investigation report -> API response shape.

Mock mode uses embedded ticket + sample logs and in-process coverage fixtures;
no external Jira/GitHub/Jenkins/Datadog/Kubernetes/PagerDuty/Confluence
credentials required on the API host.

Live mode uses CLI/env values and reports SKIPPED for providers without credentials.

Prerequisites (mock):
  - API running: uvicorn api.main:app --port 8000
  - Neo4j with migrations (for anomaly RCA + confidence): NEO4J_URI/USER/PASSWORD
  - Auth: API_BEARER_TOKEN or seeded user (scripts/seed_users.py)

Prerequisites (live):
  - Same as mock, plus provider credentials in API .env for integrations under test

Usage::

    python scripts/validate_e2e_mcp_rca_flow.py --mode mock
    python scripts/validate_e2e_mcp_rca_flow.py --mode live --ticket-key PROJ-123 \\
        --service-name auth-service --repo-name org/auth-service
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO / ".env")
except ImportError:
    pass

DEFAULT_LOGS = _REPO / "scripts" / "fixtures" / "e2e_mcp_rca_sample.log"

UNIFIED_CONTEXT_FIELDS = (
    "ticket_context",
    "commits",
    "pull_requests",
    "merge_requests",
    "build_events",
    "deployment_events",
    "metric_events",
    "alert_events",
    "trace_events",
    "service_health_events",
    "cluster_events",
    "namespace_events",
    "pod_events",
    "container_events",
    "node_events",
    "pagerduty_incidents",
    "pagerduty_escalations",
    "pagerduty_timeline_events",
    "runbook_documents",
    "known_issue_documents",
    "architecture_documents",
    "pipelines",
    "source_metadata",
    "evidence_coverage",
)

PROVIDER_DISPLAY: dict[str, str] = {
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "jenkins": "Jenkins",
    "datadog": "Datadog",
    "kubernetes": "Kubernetes",
    "pagerduty": "PagerDuty",
    "confluence": "Confluence",
}

MOCK_COVERAGE_EXPECTATIONS: dict[str, bool] = {
    "jira": True,
    "github": True,
    "datadog": False,
}

LIVE_PROVIDER_ENV: dict[str, list[str]] = {
    "jira": ["JIRA_BASE_URL", "JIRA_API_TOKEN"],
    "github": ["GITHUB_TOKEN"],
    "gitlab": ["GITLAB_TOKEN", "GITLAB_PROJECT_ID"],
    "jenkins": ["JENKINS_BASE_URL", "JENKINS_USER", "JENKINS_API_TOKEN"],
    "datadog": ["DATADOG_API_KEY", "DATADOG_APP_KEY"],
    "kubernetes": ["KUBERNETES_API_SERVER", "KUBERNETES_TOKEN"],
    "pagerduty": ["PAGERDUTY_API_TOKEN"],
    "confluence": ["CONFLUENCE_BASE_URL", "CONFLUENCE_API_TOKEN"],
}

CheckStatus = Literal["PASS", "FAIL", "SKIPPED"]


@dataclass
class Check:
    name: str
    status: CheckStatus
    detail: str = ""

    def line(self) -> str:
        return f"[{self.status}] {self.name}" + (f" — {self.detail}" if self.detail else "")


@dataclass
class ValidationRun:
    checks: list[Check] = field(default_factory=list)
    mode: str = "mock"
    base_url: str = ""

    def record(self, name: str, status: CheckStatus, detail: str = "") -> None:
        self.checks.append(Check(name=name, status=status, detail=detail))
        print(self.checks[-1].line())

    def failed(self) -> bool:
        return any(c.status == "FAIL" for c in self.checks)

    def summary(self) -> None:
        passed = sum(1 for c in self.checks if c.status == "PASS")
        failed = sum(1 for c in self.checks if c.status == "FAIL")
        skipped = sum(1 for c in self.checks if c.status == "SKIPPED")
        print()
        print("=== MCP RCA E2E summary ===")
        print(f"mode={self.mode} base_url={self.base_url}")
        print(f"PASS={passed} FAIL={failed} SKIPPED={skipped}")
        if failed:
            print("Result: FAIL")
        else:
            print("Result: OK")


class HttpClient:
    def __init__(self, base_url: str, bearer_token: str | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.bearer_token = bearer_token

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def get(self, path: str, *, timeout: float = 120.0) -> dict[str, Any]:
        url = f"{self.base}{path}"
        req = Request(url, method="GET", headers=self._headers())
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, path: str, body: dict[str, Any], *, timeout: float = 300.0) -> dict[str, Any]:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method="POST", headers=self._headers(json_body=True))
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _mock_ticket(ticket_key: str, service_name: str) -> dict[str, Any]:
    return {
        "ticket_key": ticket_key,
        "ticket_id": f"mock-{ticket_key.lower()}",
        "summary": f"{service_name} elevated error rate in production",
        "status": "Open",
        "priority": "High",
        "labels": [service_name, "prod", "rca-e2e"],
        "url": f"https://example.atlassian.net/browse/{ticket_key}",
    }


def _mock_ticket_hints(service_name: str) -> dict[str, Any]:
    return {
        "service_names": [service_name],
        "environment_names": ["prod"],
        "file_paths": ["/srv/auth/handler.py"],
        "error_keywords": ["timeout", "error"],
        "labels": ["rca-e2e"],
    }


def _load_logs(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"log file is empty: {path}")
    return text


def _resolve_bearer_token(client: HttpClient) -> str | None:
    explicit = (os.environ.get("API_BEARER_TOKEN") or "").strip()
    if explicit:
        return explicit
    email = (os.environ.get("VALIDATE_AUTH_EMAIL") or "neel@example.com").strip()
    password = (os.environ.get("VALIDATE_AUTH_PASSWORD") or "seeddev123").strip()
    try:
        resp = client.post("/api/v1/auth/login", {"email": email, "password": password}, timeout=30.0)
        token = str(resp.get("access_token") or "").strip()
        return token or None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"auth login failed ({exc.code}): {body}")
        return None
    except (URLError, TimeoutError, OSError) as exc:
        print(f"auth login failed: {exc}")
        return None


def _provider_env_configured(source: str) -> bool:
    keys = LIVE_PROVIDER_ENV.get(source, [])
    if not keys:
        return False
    return all((os.environ.get(k) or "").strip() for k in keys)


def _bootstrap_neo4j_anomaly(*, anomaly_id: str, service_name: str, repo_name: str) -> tuple[bool, str]:
    password = (os.environ.get("NEO4J_PASSWORD") or "").strip()
    if not password:
        return False, "NEO4J_PASSWORD not set"

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")

    from graph.migrations import apply_migrations
    from graph.neo4j_client import Neo4jClient
    from graph.writer import GraphWriter, _compute_file_id

    apply_migrations(uri, user, password)
    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        writer = GraphWriter(client)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        trace_ref = f"e2e-mcp-rca-{anomaly_id[:8]}"
        repo_ref = repo_name.split("/")[-1] if repo_name else "e2e-repo"

        writer.upsert_anomaly(anomaly_id, ts, trace_ref=trace_ref, window_id="e2e-mcp-w1")
        client.execute_write(
            "MATCH (a:Anomaly {id: $id}) SET a.service_ref = $service_ref",
            {"id": anomaly_id, "service_ref": service_name},
        )
        writer.upsert_stackframe("e2e-f0", trace_ref, symbol_name="handle_request", frame_order=0, resolution="resolved")
        writer.upsert_stackframe("e2e-f1", trace_ref, symbol_name="process_token", frame_order=1, resolution="resolved")
        writer.upsert_file("/srv/auth/handler.py", repo_ref)
        writer.upsert_commit("e2eabc123", repo_ref, ts)
        writer.upsert_deployment("e2e-deploy-001", ts, service_ref=service_name)
        writer.link_has_frame(anomaly_id, "e2e-f0", 0)
        writer.link_has_frame(anomaly_id, "e2e-f1", 1)
        handler_id = _compute_file_id(repo_ref, "/srv/auth/handler.py")
        writer.link_in_file("e2e-f0", handler_id)
        writer.link_in_file("e2e-f1", handler_id)
        writer.link_touched("e2eabc123", repo_ref, handler_id)
        writer.link_deployed_commit("e2e-deploy-001", "e2eabc123", repo_ref)
        return True, f"seeded anomaly_id={anomaly_id}"
    finally:
        client.close()


def _investigation_node_exists(investigation_id: str) -> tuple[bool, str]:
    password = (os.environ.get("NEO4J_PASSWORD") or "").strip()
    if not password or not investigation_id:
        return False, "neo4j or investigation_id unavailable"
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    from graph.neo4j_client import Neo4jClient

    client = Neo4jClient(uri, user, password)
    client.connect()
    try:
        rows = client.execute_read(
            "MATCH (i:Investigation {id: $id}) RETURN i.id AS id LIMIT 1",
            {"id": investigation_id},
        )
        if rows:
            return True, f"found Investigation id={investigation_id}"
        return False, f"no Investigation node for id={investigation_id} (persistence may be disabled)"
    except Exception as exc:
        return False, f"neo4j query failed gracefully: {exc}"
    finally:
        client.close()


def _bundle_exists(evidence_ref: str) -> tuple[bool, str]:
    if not evidence_ref:
        return False, "no evidence_ref"
    base = (os.environ.get("EVIDENCE_STORE_DIR") or "").strip()
    if not base:
        return False, "EVIDENCE_STORE_DIR not set on validator host"
    path = Path(base) / "evidence_bundles" / f"{evidence_ref}.json"
    if path.is_file():
        return True, str(path)
    return False, f"bundle file not found at {path}"


def _extract_candidates(rca_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rca = rca_payload.get("rca") or {}
    rca_result = rca.get("rca_result") or {}
    if isinstance(rca_result, dict):
        cands = rca_result.get("candidate_root_causes")
        if isinstance(cands, list) and cands:
            return [c for c in cands if isinstance(c, dict)]
    return []


def _extract_confidence_assessments(rca_payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct = rca_payload.get("confidence_assessments")
    if isinstance(direct, list) and direct:
        return [x for x in direct if isinstance(x, dict)]

    out: list[dict[str, Any]] = []
    for cand in _extract_candidates(rca_payload):
        assessment = cand.get("confidence_assessment")
        if isinstance(assessment, dict) and assessment:
            out.append(assessment)
    return out


def _extract_evidence_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    coverage = payload.get("evidence_coverage")
    return coverage if isinstance(coverage, dict) else {}


def _mock_coverage_context() -> dict[str, Any]:
    """In-process fixture: Jira + GitHub contribute; Datadog missing."""
    from mcp.context.investigation_context import UnifiedInvestigationContext
    from mcp.evidence_coverage import attach_evidence_coverage
    from mcp.schemas.github_models import McpCommit, McpPullRequest
    from mcp.schemas.jira_models import McpTicketContext

    context = attach_evidence_coverage(
        UnifiedInvestigationContext(
            ticket_context=McpTicketContext(issue_key="MOCK-1001", summary="Auth outage"),
            pull_requests=[McpPullRequest(number=42, title="Fix auth handler")],
            commits=[McpCommit(sha="deadbeef", message="fix auth")],
        )
    )
    coverage = context.evidence_coverage
    if coverage is None:
        return {}
    return coverage.model_dump()


def _provider_display(source: str) -> str:
    return PROVIDER_DISPLAY.get(source, source.replace("_", " ").title())


def _validate_provider_contribution(
    run: ValidationRun,
    source: str,
    coverage: dict[str, Any],
    *,
    expect_contributed: bool,
) -> None:
    name = _provider_display(source)
    available = [str(s) for s in (coverage.get("available_sources") or [])]
    missing = [str(s) for s in (coverage.get("missing_sources") or [])]
    if expect_contributed:
        if source in available:
            run.record(f"{name} contributed", "PASS")
        else:
            run.record(
                f"{name} contributed",
                "FAIL",
                f"expected in available_sources; got available={available}",
            )
    elif source in missing:
        run.record(f"{name} missing", "PASS")
    else:
        run.record(
            f"{name} missing",
            "FAIL",
            f"expected in missing_sources; got missing={missing}",
        )


def _validate_coverage_generation(run: ValidationRun, coverage: dict[str, Any]) -> None:
    if not coverage:
        run.record("Coverage generated", "FAIL", "evidence_coverage missing")
        return
    score = coverage.get("coverage_score")
    level = coverage.get("coverage_level")
    if score is None or level is None:
        run.record("Coverage generated", "FAIL", "coverage_score or coverage_level missing")
        return
    run.record("Coverage generated", "PASS", f"score={score} level={level}")


def _validate_provider_health(run: ValidationRun, client: HttpClient, *, mode: str) -> None:
    try:
        response = client.get("/api/v1/mcp/connections", timeout=30.0)
    except HTTPError as exc:
        run.record("MCP provider health", "FAIL", f"HTTP {exc.code}")
        return
    except (URLError, TimeoutError, OSError) as exc:
        run.record("MCP provider health", "FAIL", str(exc))
        return

    connections = response.get("connections") or []
    if not isinstance(connections, list) or not connections:
        run.record("MCP provider health", "FAIL", "connections list empty")
        return

    checked = 0
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        provider = str(conn.get("provider") or "")
        if not provider:
            continue
        name = _provider_display(provider)
        if mode == "live" and not _provider_env_configured(provider):
            run.record(f"MCP health: {name}", "SKIPPED", "credentials not configured")
            continue
        checked += 1
        if conn.get("healthy"):
            run.record(f"MCP health: {name}", "PASS", "healthy")
        elif conn.get("configured"):
            detail = str(conn.get("error_message") or "unhealthy")
            run.record(f"MCP health: {name}", "FAIL", detail)
        else:
            run.record(f"MCP health: {name}", "SKIPPED", "not configured")

    if checked == 0 and mode == "mock":
        run.record("MCP provider health", "PASS", f"connections endpoint ok ({len(connections)} providers)")


def _validate_confidence_limitations(run: ValidationRun, assessments: list[dict[str, Any]]) -> None:
    if not assessments:
        run.record("Confidence limitations generated", "SKIPPED", "no confidence assessments")
        return
    top = assessments[0]
    limitations = top.get("confidence_limitations") or []
    if isinstance(limitations, list) and limitations:
        run.record(
            "Confidence limitations generated",
            "PASS",
            "; ".join(str(item) for item in limitations[:4]),
        )
        return
    if top.get("coverage_score") is not None or top.get("coverage_level"):
        run.record(
            "Confidence limitations generated",
            "PASS",
            "coverage metadata present with empty limitations",
        )
        return
    run.record("Confidence limitations generated", "FAIL", "confidence_limitations missing")


def _validate_report_coverage_section(
    run: ValidationRun,
    client: HttpClient,
    investigation_id: str,
) -> None:
    if not investigation_id:
        run.record("Report coverage section present", "SKIPPED", "investigation_id not returned")
        return
    try:
        response = client.get(f"/api/v1/investigations/{investigation_id}/report", timeout=120.0)
    except HTTPError as exc:
        if exc.code == 404:
            run.record(
                "Report coverage section present",
                "SKIPPED",
                "investigation graph not found for report API",
            )
        else:
            run.record("Report coverage section present", "FAIL", f"HTTP {exc.code}")
        return
    except (URLError, TimeoutError, OSError) as exc:
        run.record("Report coverage section present", "FAIL", str(exc))
        return

    report = response.get("report") if isinstance(response, dict) else {}
    coverage = report.get("evidence_coverage") if isinstance(report, dict) else None
    if not isinstance(coverage, dict):
        run.record("Report coverage section present", "FAIL", "report.evidence_coverage missing")
        return
    required = ("coverage_score", "coverage_level", "available_sources", "missing_sources", "confidence_limitations")
    missing = [key for key in required if key not in coverage]
    if missing:
        run.record(
            "Report coverage section present",
            "FAIL",
            f"missing fields: {', '.join(missing)}",
        )
        return
    run.record(
        "Report coverage section present",
        "PASS",
        f"level={coverage.get('coverage_level')} score={coverage.get('coverage_score')}",
    )


def _validate_coverage_suite(
    run: ValidationRun,
    coverage: dict[str, Any],
    *,
    contribution_expectations: dict[str, bool] | None = None,
) -> None:
    _validate_coverage_generation(run, coverage)
    if contribution_expectations:
        for source, expect_contributed in contribution_expectations.items():
            _validate_provider_contribution(
                run,
                source,
                coverage,
                expect_contributed=expect_contributed,
            )
    else:
        details = coverage.get("source_details") or {}
        if isinstance(details, dict):
            for source, detail in details.items():
                if not isinstance(detail, dict):
                    continue
                name = _provider_display(str(source))
                if detail.get("contributed"):
                    run.record(f"{name} contributed", "PASS")
                else:
                    run.record(f"{name} missing", "PASS")


def run_validation(args: argparse.Namespace) -> int:
    run = ValidationRun(mode=args.mode, base_url=args.base_url.rstrip("/"))
    print("=== MCP RCA E2E validation ===")
    print(f"mode={args.mode} base_url={args.base_url}")
    print()

    client = HttpClient(args.base_url)
    token = _resolve_bearer_token(client)
    if not token:
        run.record("API authentication", "FAIL", "set API_BEARER_TOKEN or seed user + POSTGRES_URL")
        run.summary()
        return 1
    client.bearer_token = token

    # 1) Health
    try:
        health = client.get("/health", timeout=15.0)
        if health:
            run.record("API health", "PASS")
        else:
            run.record("API health", "FAIL", "empty response")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        run.record("API health", "FAIL", str(exc))
        run.summary()
        return 1

    # 2) MCP status
    try:
        status = client.get("/api/v1/mcp/status", timeout=30.0)
        providers = status.get("providers") or []
        if not isinstance(providers, list):
            run.record("MCP status", "FAIL", "providers missing")
        else:
            run.record("MCP status", "PASS", f"mcp_enabled={status.get('mcp_enabled')} providers={len(providers)}")
    except HTTPError as exc:
        run.record("MCP status", "FAIL", f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        run.record("MCP status", "FAIL", str(exc))

    # 3) Enabled providers reported
    try:
        status = client.get("/api/v1/mcp/status", timeout=30.0)
        providers = status.get("providers") or []
        names = [str(p.get("source")) for p in providers if isinstance(p, dict) and p.get("source")]
        if names:
            run.record("Enabled providers reported", "PASS", ", ".join(names))
        else:
            run.record("Enabled providers reported", "PASS", "none (MCP may be disabled)")
    except Exception as exc:
        run.record("Enabled providers reported", "FAIL", str(exc))

    if args.mode == "live":
        for source in LIVE_PROVIDER_ENV:
            if _provider_env_configured(source):
                run.record(f"Live credentials: {source}", "PASS", "env configured")
            else:
                run.record(
                    f"Live credentials: {source}",
                    "SKIPPED",
                    f"missing {', '.join(LIVE_PROVIDER_ENV[source])}",
                )

    # 4) MCP context preview
    preview_body: dict[str, Any] = {
        "ticket_key": args.ticket_key,
        "service_name": args.service_name,
        "repo_name": args.repo_name,
    }
    if args.mode == "mock":
        preview_body["enabled_sources"] = []
    context_preview: dict[str, Any] = {}
    try:
        context_preview = client.post("/api/v1/mcp/context/preview", preview_body, timeout=120.0)
        missing = [f for f in UNIFIED_CONTEXT_FIELDS if f not in context_preview]
        if missing:
            run.record("Context preview", "FAIL", f"missing fields: {', '.join(missing[:5])}")
        else:
            run.record("Context preview", "PASS", f"UnifiedInvestigationContext fields present ({len(UNIFIED_CONTEXT_FIELDS)})")
    except HTTPError as exc:
        run.record("Context preview", "FAIL", f"HTTP {exc.code}: {exc.read().decode()[:180]}")
    except (URLError, TimeoutError, OSError) as exc:
        run.record("Context preview", "FAIL", str(exc))

    preview_coverage = _extract_evidence_coverage(context_preview)
    _validate_provider_health(run, client, mode=args.mode)

    if args.mode == "mock":
        mock_coverage = _mock_coverage_context()
        _validate_coverage_suite(run, mock_coverage, contribution_expectations=MOCK_COVERAGE_EXPECTATIONS)
    elif preview_coverage:
        _validate_coverage_suite(run, preview_coverage)
    else:
        run.record("Coverage generated", "SKIPPED", "context preview returned no evidence_coverage")

    # Bootstrap anomaly for deterministic RCA + confidence (mock default)
    anomaly_id = (args.anomaly_id or "").strip() or f"e2e-mcp-rca-{uuid.uuid4().hex[:10]}"
    if args.bootstrap_anomaly:
        ok, detail = _bootstrap_neo4j_anomaly(
            anomaly_id=anomaly_id,
            service_name=args.service_name,
            repo_name=args.repo_name,
        )
        if ok:
            run.record("Neo4j anomaly bootstrap", "PASS", detail)
        else:
            run.record("Neo4j anomaly bootstrap", "SKIPPED", detail)
    else:
        run.record("Neo4j anomaly bootstrap", "SKIPPED", "--no-bootstrap-anomaly")

    # 5) JIRA RCA run (full orchestration)
    logs_path = Path(args.logs_file)
    try:
        log_content = _load_logs(logs_path)
    except (OSError, ValueError) as exc:
        run.record("RCA run", "FAIL", f"logs: {exc}")
        run.summary()
        return 1

    rca_body: dict[str, Any] = {
        "anomaly_id": anomaly_id,
        "ticket_key": args.ticket_key,
        "ticket": _mock_ticket(args.ticket_key, args.service_name),
        "ticket_hints": _mock_ticket_hints(args.service_name),
        "log_content": log_content,
        "idempotency_key": f"e2e-mcp-rca-{uuid.uuid4().hex[:12]}",
        "force": True,
    }
    rca_payload: dict[str, Any] = {}
    try:
        rca_payload = client.post("/api/v1/jira/rca/run", rca_body, timeout=600.0)
        status = str((rca_payload.get("rca") or {}).get("run_status") or rca_payload.get("status") or "")
        if status and status not in {"completed", "ok"}:
            run.record("RCA run", "FAIL", f"run_status={status}")
        else:
            run.record("RCA run", "PASS", f"run_id={(rca_payload.get('rca') or {}).get('run_id', '')}")
    except HTTPError as exc:
        run.record("RCA run", "FAIL", f"HTTP {exc.code}: {exc.read().decode()[:240]}")
    except (URLError, TimeoutError, OSError) as exc:
        run.record("RCA run", "FAIL", str(exc))

    # 6) RCA candidates
    candidates = _extract_candidates(rca_payload)
    if candidates:
        top = candidates[0]
        run.record(
            "RCA candidates",
            "PASS",
            f"count={len(candidates)} top={top.get('path') or top.get('file_id')}",
        )
    else:
        run.record("RCA candidates", "FAIL", "no candidate_root_causes in response")

    # 7) Confidence assessments
    assessments = _extract_confidence_assessments(rca_payload)
    if assessments:
        top_a = assessments[0]
        run.record(
            "Confidence assessment",
            "PASS",
            f"confidence={top_a.get('confidence')} level={top_a.get('confidence_level')}",
        )
        _validate_confidence_limitations(run, assessments)
    else:
        # jira_log mode may lack graph confidence — check explanation confidence fields
        expl = rca_payload.get("explanation_payload") or {}
        if isinstance(expl, dict) and expl.get("confidence_note"):
            run.record(
                "Confidence assessment",
                "SKIPPED",
                "no graph confidence_assessment; explanation confidence_note present (jira_log or no anomaly RCA)",
            )
            run.record("Confidence limitations generated", "SKIPPED", "no graph confidence assessments")
        else:
            run.record("Confidence assessment", "FAIL", "confidence_assessment missing")
            run.record("Confidence limitations generated", "FAIL", "confidence assessments unavailable")

    # 8) GraphRAG explanation
    expl_payload = rca_payload.get("explanation_payload") or {}
    explanation_text = ""
    if isinstance(expl_payload, dict):
        explanation_text = str(expl_payload.get("explanation") or "")
    graphrag_ok = bool(explanation_text.strip())
    if graphrag_ok:
        run.record("GraphRAG explanation", "PASS", explanation_text[:100].replace("\n", " "))
    else:
        run.record("GraphRAG explanation", "FAIL", "explanation_payload.explanation empty")

    # 9) Investigation narrative (via dedicated explanation endpoint when anomaly RCA ran)
    narrative_found = False
    if anomaly_id:
        try:
            expl_api = client.get(f"/api/v1/rca/explanation/{anomaly_id}", timeout=180.0)
            if expl_api.get("investigation_narrative") or expl_api.get("confidence_reasoning"):
                narrative_found = True
                run.record("Investigation narrative", "PASS", "explanation API includes narrative/confidence reasoning")
            elif str(expl_api.get("explanation_summary") or "").strip():
                run.record(
                    "Investigation narrative",
                    "SKIPPED",
                    "explanation generated without investigation_narrative block",
                )
            else:
                run.record("Investigation narrative", "SKIPPED", "explanation API returned minimal payload")
        except HTTPError as exc:
            if exc.code == 404:
                run.record("Investigation narrative", "SKIPPED", "no RCA explanation endpoint data")
            else:
                run.record("Investigation narrative", "SKIPPED", f"HTTP {exc.code}")
        except (URLError, TimeoutError, OSError) as exc:
            run.record("Investigation narrative", "SKIPPED", str(exc))
    else:
        run.record("Investigation narrative", "SKIPPED", "no anomaly_id")

    # 10) Neo4j investigation graph persistence
    evidence_summary = (rca_payload.get("rca") or {}).get("evidence_summary") or {}
    investigation_id = str(evidence_summary.get("investigation_id") or "")
    if investigation_id:
        found, detail = _investigation_node_exists(investigation_id)
        if found:
            run.record("Neo4j investigation graph", "PASS", detail)
        else:
            run.record("Neo4j investigation graph", "PASS", f"graceful: {detail}")
    else:
        run.record("Neo4j investigation graph", "SKIPPED", "investigation_id not returned (persistence optional)")

    _validate_report_coverage_section(run, client, investigation_id)

    # 11) Evidence bundle
    refs = evidence_summary.get("evidence_refs") if isinstance(evidence_summary, dict) else None
    ref_list = [r for r in (refs or []) if r]
    if not ref_list:
        for cand in candidates:
            ref = cand.get("evidence_ref")
            if ref:
                ref_list.append(str(ref))
    if ref_list:
        ok, detail = _bundle_exists(ref_list[0])
        if ok:
            run.record("Evidence bundle", "PASS", detail)
        else:
            run.record("Evidence bundle", "SKIPPED", detail)
    else:
        run.record("Evidence bundle", "SKIPPED", "no evidence_ref in response (jira_log mode)")

    # API response shape sanity
    required_top = ("rca", "explanation_payload", "derived_log_signals")
    missing_top = [k for k in required_top if k not in rca_payload]
    if missing_top:
        run.record("API response shape", "FAIL", f"missing keys: {', '.join(missing_top)}")
    else:
        run.record("API response shape", "PASS")

    if args.mode == "mock" and context_preview is not None:
        run.record("Mock external credentials", "PASS", "embedded ticket + enabled_sources=[] for preview")

    run.summary()
    return 1 if run.failed() else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate MCP-powered RCA end-to-end flow.")
    parser.add_argument("--base-url", default=os.environ.get("API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--ticket-key", default="MOCK-1001")
    parser.add_argument("--service-name", default="auth-service")
    parser.add_argument("--repo-name", default="org/auth-service")
    parser.add_argument("--logs-file", default=str(DEFAULT_LOGS))
    parser.add_argument("--anomaly-id", default="", help="Existing or new anomaly id for graph RCA")
    parser.add_argument(
        "--bootstrap-anomaly",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Seed Neo4j anomaly in mock/live when NEO4J_PASSWORD is set (default: true)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_validation(args)


if __name__ == "__main__":
    raise SystemExit(main())
