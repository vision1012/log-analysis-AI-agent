#!/usr/bin/env python3
"""
Dump FastAPI route inventory for runtime vs source audits.

Usage:
    python scripts/debug_routes.py
    python scripts/debug_routes.py --output artifacts/debug/runtime_routes.txt
    python scripts/debug_routes.py --openapi artifacts/debug/runtime_openapi_paths.txt

Inside Docker:
    docker compose exec api python scripts/debug_routes.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _REPO / "artifacts" / "debug" / "runtime_routes.txt"

# Routes the Integrations UI and auth flows depend on.
EXPECTED_PATHS: tuple[str, ...] = (
    "/health",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/integrations/connections",
    "/api/v1/mcp/status",
    "/api/v1/mcp/connections",
    "/api/v1/jobs",
    "/api/v1/feedback/confirm",
)


def _collect_route_lines(app) -> list[str]:
    lines: list[str] = []
    openapi_paths = sorted(app.openapi().get("paths", {}).keys())
    lines.append(f"# route_count={len(openapi_paths)}")
    lines.append("")
    lines.append("## app.routes (leaf paths)")
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            for method in sorted(methods):
                if method in {"HEAD", "OPTIONS"}:
                    continue
                lines.append(f"{method:7} {path}")
    lines.append("")
    lines.append("## openapi paths")
    for path in openapi_paths:
        lines.append(path)
    return lines


def _expected_audit(app, openapi_paths: set[str]) -> list[str]:
    route_paths = {getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)}
    lines = ["", "## expected path audit"]
    for path in EXPECTED_PATHS:
        present = path in openapi_paths or path in route_paths
        if present:
            lines.append(f"PASS    {path}")
        else:
            lines.append(f"MISSING {path}")
    extras = sorted(p for p in openapi_paths if p.startswith("/api/v1/integrations"))
    lines.append("")
    lines.append("## integration paths present")
    if extras:
        lines.extend(extras)
    else:
        lines.append("(none)")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump FastAPI runtime route inventory.")
    parser.add_argument(
        "--output",
        default=str(_DEFAULT_OUT),
        help="Write human-readable route list to this file",
    )
    parser.add_argument(
        "--openapi",
        default="",
        help="Optional: write sorted OpenAPI paths only to this file",
    )
    args = parser.parse_args()

    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))

    from api.main import app

    openapi_paths = set(app.openapi().get("paths", {}).keys())
    lines = _collect_route_lines(app)
    lines.extend(_expected_audit(app, openapi_paths))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(openapi_paths)} openapi paths)")

    if args.openapi:
        openapi_out = Path(args.openapi)
        openapi_out.parent.mkdir(parents=True, exist_ok=True)
        openapi_out.write_text(
            "\n".join(sorted(openapi_paths)) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {openapi_out}")

    route_paths = {getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)}
    missing = [p for p in EXPECTED_PATHS if p not in openapi_paths and p not in route_paths]
    if missing:
        print("MISSING expected paths:", ", ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
