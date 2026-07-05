"""MCP UnifiedInvestigationContext signals for additive RCA scoring."""

from __future__ import annotations

import os
from typing import Any

MCP_CONTEXT_SIGNAL_NAMES = (
    "recent_commit_match",
    "recent_pr_match",
    "changed_file_match",
    "jira_ticket_match",
    "jira_label_match",
    "author_activity_match",
)

# Max additive boost for jira_log ranking (does not replace log signals).
JIRA_LOG_MCP_BOOST_CAP = 0.25

# Per-signal contribution caps for jira_log additive boost.
JIRA_LOG_MCP_SIGNAL_WEIGHTS: dict[str, float] = {
    "recent_commit_match": 0.06,
    "recent_pr_match": 0.05,
    "changed_file_match": 0.07,
    "jira_ticket_match": 0.03,
    "jira_label_match": 0.02,
    "author_activity_match": 0.04,
}


def _basename(path: str) -> str:
    return os.path.basename((path or "").strip()).lower()


def _path_tokens(path: str) -> set[str]:
    p = (path or "").lower().replace("\\", "/")
    parts = [seg for seg in p.split("/") if seg and seg not in {".", ".."}]
    base = _basename(p)
    tokens = set(parts)
    if base:
        tokens.add(base)
        if "." in base:
            tokens.add(base.rsplit(".", 1)[0])
    return tokens


def _text_contains_path(text: str, path: str) -> bool:
    if not text or not path:
        return False
    lowered = text.lower()
    if path.lower() in lowered:
        return True
    base = _basename(path)
    return bool(base and base in lowered)


def _model_list(obj: Any, attr: str) -> list[Any]:
    if obj is None:
        return []
    value = getattr(obj, attr, None)
    return list(value or [])


def _commit_changed_files(commit: Any) -> list[str]:
    files = getattr(commit, "changed_files", None) or []
    return [str(f) for f in files if f]


def _pr_changed_files(pr: Any) -> list[str]:
    files = getattr(pr, "changed_files", None) or []
    return [str(f) for f in files if f]


def normalize_candidate_path(path: str) -> str:
    """Normalize absolute or repo-relative paths for GitHub changed_files matching."""
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    lowered = raw.lower()
    for marker in ("/src/", "src/"):
        idx = lowered.find(marker)
        if idx >= 0:
            return raw[idx + (1 if marker.startswith("/") else 0) :]
    return raw


def _pr_matches_investigation_keywords(title: str, *, jira_key: str) -> bool:
    text = (title or "").lower()
    if not text:
        return False
    key = (jira_key or "").strip().lower()
    if key and key in text:
        return True
    return any(term in text for term in ("integration", "settings", "github"))


def _path_matches_changed_files(path: str, changed_files: list[str]) -> bool:
    if not path or not changed_files:
        return False
    path_l = path.lower()
    base = _basename(path)
    for raw in changed_files:
        cf = (raw or "").strip().lower()
        if not cf:
            continue
        if cf == path_l or cf.endswith("/" + base) or base == _basename(cf):
            return True
        if path_l.endswith(cf) or cf.endswith(path_l):
            return True
    return False


def compute_mcp_context_signals_for_path(
    path: str,
    unified_context: Any | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """
    Compute additive MCP context signals for one candidate path.

    Returns (signal_values, artifact_refs). All signals are in [0, 1].
    When unified_context is None/empty, returns zeros and empty refs.
    """
    empty_signals = {name: 0.0 for name in MCP_CONTEXT_SIGNAL_NAMES}
    empty_refs: dict[str, Any] = {
        "jira_ticket_key": "",
        "jira_ticket_summary": "",
        "jira_status": "",
        "jira_labels": [],
        "matched_commits": [],
        "matched_pull_requests": [],
        "matched_changed_files": [],
        "mcp_sources_used": [],
    }
    if unified_context is None:
        return empty_signals, empty_refs

    commits = _model_list(unified_context, "commits")
    pull_requests = _model_list(unified_context, "pull_requests")
    ticket = getattr(unified_context, "ticket_context", None)
    source_metadata = _model_list(unified_context, "source_metadata")

    if not commits and not pull_requests and ticket is None:
        return empty_signals, empty_refs

    normalized_path = normalize_candidate_path(path)
    match_path = normalized_path or path
    path_l = (match_path or "").lower()
    path_base = _basename(match_path)
    path_tokens = _path_tokens(match_path)
    jira_key = str(getattr(ticket, "issue_key", "") or "") if ticket is not None else ""

    matched_commits: list[dict[str, str]] = []
    matched_prs: list[dict[str, str]] = []
    matched_files: list[str] = []
    matched_authors: set[str] = set()

    recent_commit_match = 0.0
    changed_file_match = 0.0
    author_activity_match = 0.0

    for commit in commits[:50]:
        sha = str(getattr(commit, "sha", "") or getattr(commit, "id", "") or "")
        author = str(getattr(commit, "author", "") or "")
        changed = _commit_changed_files(commit)
        message = str(getattr(commit, "message", "") or getattr(commit, "title", "") or "")

        file_hit = _path_matches_changed_files(match_path, changed)
        msg_hit = _text_contains_path(message, match_path)
        if file_hit or msg_hit:
            recent_commit_match = max(recent_commit_match, 1.0)
            matched_commits.append({"sha": sha[:12], "author": author})
            for cf in changed:
                if _path_matches_changed_files(match_path, [cf]):
                    if cf not in matched_files:
                        matched_files.append(cf)
            if author:
                matched_authors.add(author.lower())

        if file_hit:
            changed_file_match = max(changed_file_match, 1.0)
        elif changed and path_base:
            for cf in changed:
                if path_base in cf.lower():
                    changed_file_match = max(changed_file_match, 0.6)
                    break

    recent_pr_match_val = 0.0
    for pr in pull_requests[:20]:
        number = str(getattr(pr, "number", "") or "")
        author = str(getattr(pr, "author", "") or "")
        title = str(getattr(pr, "title", "") or "")
        changed = _pr_changed_files(pr)
        file_hit = _path_matches_changed_files(match_path, changed)
        title_hit = _text_contains_path(title, match_path)
        keyword_hit = _pr_matches_investigation_keywords(title, jira_key=jira_key)
        pr_match = 1.0 if file_hit else (0.5 if title_hit else (0.7 if keyword_hit else 0.0))

        if pr_match > 0:
            recent_pr_match_val = max(recent_pr_match_val, pr_match)
            matched_prs.append({"number": number, "author": author, "title": title[:120]})
            if author:
                matched_authors.add(author.lower())
            for cf in changed:
                if _path_matches_changed_files(match_path, [cf]) and cf not in matched_files:
                    matched_files.append(cf)

        if file_hit:
            changed_file_match = max(changed_file_match, 1.0)
            recent_commit_match = max(recent_commit_match, 1.0)
        elif changed and path_base:
            for cf in changed:
                if path_base in cf.lower():
                    changed_file_match = max(changed_file_match, 0.6)
                    break

    if changed_file_match > 0 and recent_commit_match == 0.0:
        recent_commit_match = changed_file_match

    if path_base and matched_authors:
        for author in matched_authors:
            if author and (author in path_l or any(author in cf.lower() for cf in matched_files)):
                author_activity_match = 1.0
                break
        if author_activity_match == 0.0 and matched_authors:
            author_activity_match = 0.5

    jira_ticket_match = 0.0
    jira_label_match = 0.0
    jira_key = ""
    jira_summary = ""
    jira_status = ""
    jira_labels: list[str] = []

    if ticket is not None:
        jira_key = str(getattr(ticket, "issue_key", "") or "")
        jira_summary = str(getattr(ticket, "summary", "") or "")
        jira_status = str(getattr(ticket, "status", "") or "")
        jira_labels = [str(l) for l in (getattr(ticket, "labels", None) or []) if l]
        description = str(getattr(ticket, "description", "") or "")

        if _text_contains_path(jira_summary, match_path) or _text_contains_path(description, match_path):
            jira_ticket_match = 1.0
        else:
            ticket_text = f"{jira_summary} {description}".lower()
            overlap = path_tokens & set(ticket_text.split())
            if overlap:
                jira_ticket_match = min(1.0, 0.3 + 0.1 * len(overlap))

        for label in jira_labels:
            token = label.lower().strip()
            if not token:
                continue
            if token in path_l or token in path_tokens:
                jira_label_match = 1.0
                break
            for part in token.replace("_", "-").split("-"):
                part = part.strip()
                if len(part) > 2 and part in path_l:
                    jira_label_match = 1.0
                    break
            if jira_label_match >= 1.0:
                break
            if len(token) > 3 and token in f"{jira_summary} {description}".lower() and path_base:
                jira_label_match = max(jira_label_match, 0.4)

    mcp_sources = sorted(
        {
            str(getattr(m, "source", "") or "")
            for m in source_metadata
            if getattr(m, "ok", False)
        }
        - {""}
    )

    signals = {
        "recent_commit_match": recent_commit_match,
        "recent_pr_match": recent_pr_match_val,
        "changed_file_match": changed_file_match,
        "jira_ticket_match": jira_ticket_match,
        "jira_label_match": jira_label_match,
        "author_activity_match": author_activity_match,
    }
    refs = {
        "jira_ticket_key": jira_key,
        "jira_ticket_summary": jira_summary[:300],
        "jira_status": jira_status,
        "jira_labels": jira_labels[:20],
        "matched_commits": matched_commits[:10],
        "matched_pull_requests": matched_prs[:10],
        "matched_changed_files": matched_files[:20],
        "mcp_sources_used": mcp_sources,
    }
    return signals, refs


def jira_log_mcp_boost(signals: dict[str, float]) -> float:
    """Additive score boost for jira_log ranking; zero when no MCP matches."""
    if not signals:
        return 0.0
    boost = 0.0
    for name, weight in JIRA_LOG_MCP_SIGNAL_WEIGHTS.items():
        value = float(signals.get(name) or 0.0)
        if value > 0:
            boost += value * weight
    return min(JIRA_LOG_MCP_BOOST_CAP, boost)


def mcp_context_has_data(unified_context: Any | None) -> bool:
    if unified_context is None:
        return False
    return bool(
        _model_list(unified_context, "commits")
        or _model_list(unified_context, "pull_requests")
        or getattr(unified_context, "ticket_context", None)
    )


def build_mcp_evidence_bundle_fields(
    artifact_refs: dict[str, Any],
    *,
    mcp_signal_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evidence bundle MCP reference block (no secrets)."""
    out = {
        "jira_ticket_key": artifact_refs.get("jira_ticket_key") or "",
        "jira_ticket_summary": artifact_refs.get("jira_ticket_summary") or "",
        "jira_status": artifact_refs.get("jira_status") or "",
        "jira_labels": list(artifact_refs.get("jira_labels") or []),
        "matched_commits": list(artifact_refs.get("matched_commits") or []),
        "matched_pull_requests": list(artifact_refs.get("matched_pull_requests") or []),
        "matched_changed_files": list(artifact_refs.get("matched_changed_files") or []),
        "mcp_sources_used": list(artifact_refs.get("mcp_sources_used") or []),
    }
    if mcp_signal_scores:
        out["mcp_context_signals"] = dict(mcp_signal_scores)
    return out
