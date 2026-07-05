"""Configuration for Deterministic MCP Signal Engine v2."""

from __future__ import annotations

import os

MCP_SIGNAL_V2_NAMES = (
    "code_ownership",
    "code_churn",
    "deployment_proximity_v2",
    "rollback",
    "build_failure",
    "service_dependency",
    "incident_recurrence",
    "alert_correlation_v2",
    "reviewer",
    "author_expertise",
)

# Normalized ranking weights (merged into effective_weights; env override MCP_V2_WEIGHT_*).
MCP_SIGNAL_V2_DEFAULT_WEIGHTS: dict[str, float] = {
    "code_ownership": 0.025,
    "code_churn": 0.03,
    "deployment_proximity_v2": 0.03,
    "rollback": 0.025,
    "build_failure": 0.025,
    "service_dependency": 0.02,
    "incident_recurrence": 0.025,
    "alert_correlation_v2": 0.03,
    "reviewer": 0.02,
    "author_expertise": 0.025,
}

# Additive jira_log boost weights (cap applied in engine).
JIRA_LOG_V2_BOOST_WEIGHTS: dict[str, float] = {
    "code_ownership": 0.04,
    "code_churn": 0.05,
    "deployment_proximity_v2": 0.05,
    "rollback": 0.06,
    "build_failure": 0.05,
    "service_dependency": 0.04,
    "incident_recurrence": 0.05,
    "alert_correlation_v2": 0.05,
    "reviewer": 0.03,
    "author_expertise": 0.04,
}

JIRA_LOG_V2_BOOST_CAP = 0.30


def mcp_signal_v2_enabled() -> bool:
    raw = (os.environ.get("MCP_SIGNAL_V2_ENABLED") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def churn_windows_days() -> tuple[int, ...]:
    raw = (os.environ.get("MCP_CHURN_WINDOWS_DAYS") or "7,30,90").strip()
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            days = int(part)
        except ValueError:
            continue
        if days > 0:
            out.append(days)
    return tuple(out or (7, 30, 90))


def churn_high_watermark() -> int:
    raw = (os.environ.get("MCP_CHURN_HIGH_WATERMARK") or "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


def signal_v2_weights() -> dict[str, float]:
    weights: dict[str, float] = {}
    for name, default in MCP_SIGNAL_V2_DEFAULT_WEIGHTS.items():
        env_name = f"MCP_V2_WEIGHT_{name.upper()}"
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            weights[name] = default
            continue
        try:
            weights[name] = float(raw)
        except ValueError:
            weights[name] = default
    return weights
