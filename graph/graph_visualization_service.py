"""
Investigation graph visualization — read-only nodes/edges for UI rendering.

Traverses the MCP investigation subgraph in Neo4j from a root Investigation node.
Does not modify RCA or GraphRAG behavior.
"""

from __future__ import annotations

from typing import Any

from graph.neo4j_client import Neo4jClient

VISUALIZATION_NODE_TYPES = frozenset(
    {
        "Investigation",
        "JiraTicket",
        "PullRequest",
        "Commit",
        "Build",
        "Deployment",
        "MetricEvent",
        "AlertEvent",
        "PagerDutyIncident",
        "Runbook",
        "KnownIssue",
        "Service",
        "Pod",
        "Node",
        "Feedback",
        "RCACandidate",
    }
)

LABEL_ALIASES: dict[str, str] = {
    "MergeRequest": "PullRequest",
}

RELATIONSHIP_TYPE_MAP: dict[str, str] = {
    "HAS_JIRA_TICKET": "RELATED_TO",
    "HAS_COMMIT": "RELATED_TO",
    "TRIGGERED_BUILD": "TRIGGERED_BUILD",
    "PRODUCED_DEPLOYMENT": "DEPLOYED_AS",
    "OBSERVED_METRIC": "GENERATED",
    "TRIGGERED_ALERT": "TRIGGERED",
    "ESCALATED_TO": "CAUSED",
    "AFFECTED_POD": "RELATED_TO",
    "HAS_CONTAINER": "PART_OF",
    "RUNS_ON": "PART_OF",
    "HAS_RUNBOOK": "HAS_RUNBOOK",
    "MATCHES_KNOWN_ISSUE": "MATCHES_KNOWN_ISSUE",
    "HAS_ARCHITECTURE_DOC": "RELATED_TO",
    "HAS_FEEDBACK": "HAS_FEEDBACK",
    "TARGETS_CANDIDATE": "TARGETS_CANDIDATE",
}

DEFAULT_EDGE_TYPE = "RELATED_TO"
MIN_DEPTH = 1
MAX_DEPTH = 3
DEFAULT_DEPTH = 2


def _clamp_depth(depth: int | None) -> int:
    if depth is None:
        return DEFAULT_DEPTH
    try:
        value = int(depth)
    except (TypeError, ValueError):
        return DEFAULT_DEPTH
    return max(MIN_DEPTH, min(MAX_DEPTH, value))


def _primary_label(labels: list[str]) -> str:
    for label in labels:
        if label in VISUALIZATION_NODE_TYPES:
            return label
        if label in LABEL_ALIASES:
            return LABEL_ALIASES[label]
    return labels[0] if labels else "Unknown"


def _node_key(node_type: str, props: dict[str, Any]) -> str:
    if node_type == "Investigation":
        return str(props.get("id") or "")
    if node_type == "JiraTicket":
        return str(props.get("issue_key") or props.get("id") or "")
    if node_type == "Commit":
        return str(props.get("sha") or "")
    if node_type == "Service":
        return str(props.get("name") or "")
    if node_type == "Feedback":
        return str(props.get("feedback_id") or props.get("id") or "")
    if node_type == "RCACandidate":
        return str(props.get("candidate_id") or props.get("id") or "")
    return str(props.get("id") or props.get("sha") or props.get("issue_key") or props.get("name") or "")


def _node_label(props: dict[str, Any], node_type: str) -> str:
    for key in (
        "title",
        "summary",
        "message",
        "name",
        "issue_key",
        "sha",
        "pod_name",
        "node_name",
        "comments",
        "feedback_type",
        "candidate_id",
    ):
        value = props.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text[:120]
    return node_type


def _map_edge_type(neo4j_type: str) -> str:
    return RELATIONSHIP_TYPE_MAP.get(neo4j_type, DEFAULT_EDGE_TYPE)


def _build_node(node_type: str, props: dict[str, Any]) -> dict[str, Any] | None:
    if node_type not in VISUALIZATION_NODE_TYPES:
        return None
    node_id = _node_key(node_type, props)
    if not node_id:
        return None
    return {
        "id": node_id,
        "type": node_type,
        "label": _node_label(props, node_type),
        "properties": {k: v for k, v in props.items() if v is not None},
    }


def investigation_exists(client: Neo4jClient, investigation_id: str) -> bool:
    rows = client.execute_read(
        "MATCH (i:Investigation {id: $investigation_id}) RETURN i.id AS id LIMIT 1",
        {"investigation_id": investigation_id},
    )
    return bool(rows)


def get_investigation_graph(
    client: Neo4jClient,
    investigation_id: str,
    *,
    depth: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Return visualization-ready nodes and edges for one investigation subgraph.

    Args:
        client: Connected Neo4j client.
        investigation_id: Root Investigation node id.
        depth: Traversal depth (1–3 hops from Investigation, inclusive).

    Returns:
        {"nodes": [...], "edges": [...]}
    """
    hops = _clamp_depth(depth)
    node_rows = client.execute_read(
        f"""
        MATCH (root:Investigation {{id: $investigation_id}})
        MATCH (root)-[*0..{hops}]-(n)
        WITH collect(DISTINCT n) AS node_set
        UNWIND node_set AS n
        RETURN labels(n) AS labels, properties(n) AS props
        """,
        {"investigation_id": investigation_id},
    )

    edge_rows = client.execute_read(
        f"""
        MATCH (root:Investigation {{id: $investigation_id}})
        MATCH (root)-[*0..{hops}]-(n)
        WITH collect(DISTINCT n) AS node_set
        UNWIND node_set AS a
        MATCH (a)-[r]-(b)
        WHERE b IN node_set AND elementId(a) < elementId(b)
        RETURN type(r) AS rel_type,
               labels(a) AS src_labels,
               properties(a) AS src_props,
               labels(b) AS tgt_labels,
               properties(b) AS tgt_props
        """,
        {"investigation_id": investigation_id},
    )

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for row in node_rows:
        labels = list(row.get("labels") or [])
        props = dict(row.get("props") or {})
        node_type = _primary_label(labels)
        node = _build_node(node_type, props)
        if node:
            nodes_by_id[node["id"]] = node

    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for row in edge_rows:
        src_type = _primary_label(list(row.get("src_labels") or []))
        tgt_type = _primary_label(list(row.get("tgt_labels") or []))
        src_props = dict(row.get("src_props") or {})
        tgt_props = dict(row.get("tgt_props") or {})
        src_id = _node_key(src_type, src_props)
        tgt_id = _node_key(tgt_type, tgt_props)
        if not src_id or not tgt_id:
            continue
        if src_id not in nodes_by_id or tgt_id not in nodes_by_id:
            continue
        edge_type = _map_edge_type(str(row.get("rel_type") or ""))
        key = (src_id, tgt_id, edge_type)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(
            {
                "id": f"{src_id}->{tgt_id}:{edge_type}",
                "source": src_id,
                "target": tgt_id,
                "type": edge_type,
                "relationship": str(row.get("rel_type") or ""),
            }
        )

    nodes = sorted(nodes_by_id.values(), key=lambda n: (n.get("type", ""), n.get("id", "")))
    edges.sort(key=lambda e: (e.get("type", ""), e.get("source", ""), e.get("target", "")))
    return {"nodes": nodes, "edges": edges}
