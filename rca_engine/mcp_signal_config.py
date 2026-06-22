"""Configurable point weights for MCP-derived RCA signals."""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = True) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def mcp_rca_signals_enabled() -> bool:
    return _env_bool("MCP_RCA_SIGNALS_ENABLED", default=True)


def deployment_proximity_points(bucket: str) -> int:
    mapping = {
        "0_5": _env_int("MCP_DEPLOYMENT_PROXIMITY_POINTS_0_5_MIN", 12),
        "5_15": _env_int("MCP_DEPLOYMENT_PROXIMITY_POINTS_5_15_MIN", 8),
        "15_30": _env_int("MCP_DEPLOYMENT_PROXIMITY_POINTS_15_30_MIN", 4),
    }
    return mapping.get(bucket, 0)


def alert_correlation_points(severity: str, *, repeated: bool = False) -> int:
    sev = (severity or "").strip().lower()
    if sev in {"critical", "high", "sev1"}:
        points = _env_int("MCP_ALERT_CRITICAL_POINTS", 10)
    elif sev in {"warning", "medium", "warn", "sev2"}:
        points = _env_int("MCP_ALERT_WARNING_POINTS", 5)
    else:
        points = _env_int("MCP_ALERT_INFO_POINTS", 2)
    if repeated:
        points += _env_int("MCP_ALERT_REPEATED_BONUS_POINTS", 3)
    return points


def incident_severity_points(urgency: str) -> int:
    u = (urgency or "").strip().lower()
    if u in {"high", "critical", "sev1"}:
        return _env_int("MCP_INCIDENT_HIGH_URGENCY_POINTS", 8)
    if u in {"low", "sev3"}:
        return _env_int("MCP_INCIDENT_LOW_URGENCY_POINTS", 2)
    return _env_int("MCP_INCIDENT_MEDIUM_URGENCY_POINTS", 5)


def known_issue_match_points() -> int:
    return _env_int("MCP_KNOWN_ISSUE_MATCH_POINTS", 8)


def historical_investigation_points(similarity: float) -> int:
    base = _env_int("MCP_HISTORICAL_INVESTIGATION_POINTS", 6)
    if similarity >= 1.0:
        return base + _env_int("MCP_HISTORICAL_INVESTIGATION_EXACT_BONUS", 4)
    if similarity >= 0.7:
        return base
    if similarity > 0:
        return max(1, int(base * similarity))
    return 0


def mcp_point_scale() -> float:
    """Divisor converting point contributions to score delta (default 100)."""
    scale = _env_int("MCP_RCA_POINT_SCALE", 100)
    return float(max(1, scale))
