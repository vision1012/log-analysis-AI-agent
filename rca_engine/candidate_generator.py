"""
Candidate file generation from graph traversal.

Anomaly -> HAS_FRAME -> StackFrame -> IN_FILE -> File.
Excludes unresolved/vendor/stdlib. Limits to first 5 frames. Deduplicates by file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# Resolution values that contribute to candidates (exclude unresolved)
VALID_RESOLUTIONS = ("exact", "probable", "resolved")

# Path exclusion patterns (stdlib/vendor)
PATH_EXCLUSION_PATTERNS = (
    "node_modules/",
    "vendor/",
    "site-packages/",
    "lib/python",
    "node:internal",
    "node:internal",
    "runtime.",
    "java.",
    "sun.",
    "jdk.",
)

# Limit frame scan to first N frames
FRAME_SCAN_LIMIT = 5


@dataclass
class RepresentativeFrame:
    """Representative stack frame for a candidate file."""

    frame_id: str
    frame_order: int
    symbol_name: Optional[str] = None


@dataclass
class Candidate:
    """A candidate file for RCA scoring: (file_id, representative_frame)."""

    file_id: str
    representative_frame: RepresentativeFrame
    path: str = ""
    repo_ref: str = ""
    type: str = "file"
    value: str = ""
    reason: str = ""
    score: float = 1.0

    @property
    def representative_frame_id(self) -> str:
        return self.representative_frame.frame_id

    @property
    def representative_frame_order(self) -> int:
        return self.representative_frame.frame_order

    @property
    def symbol_name(self) -> Optional[str]:
        return self.representative_frame.symbol_name


def _is_excluded_path(path: str) -> bool:
    """True if path matches stdlib/vendor exclusion patterns."""
    if not path:
        return True
    for pat in PATH_EXCLUSION_PATTERNS:
        if pat in path:
            return True
    return False


def generate_candidates(
    client: Neo4jClient,
    anomaly_id: str,
    *,
    K_frames: int = FRAME_SCAN_LIMIT,
    max_depth: int = 20,
    excluded_deployment_ids: Optional[list[str]] = None,
    signals: Optional[dict[str, Any]] = None,
) -> list[Candidate]:
    """
    Generate candidate files from graph traversal.

    Query: Anomaly -> HAS_FRAME -> StackFrame -> IN_FILE -> File.
    Orders by frame_order. Excludes unresolved/vendor/stdlib files.
    Limits frame scan to first 5 frames. Deduplicates by file_id.

    Returns:
        List of Candidate (file_id, representative_frame), deduplicated, capped at K_frames.
    """
    logger.info(
        "candidate_generator.start",
        extra={
            "anomaly_id": anomaly_id,
            "frame_scan_limit": K_frames,
            "max_depth": max_depth,
        },
    )

    q = """
    MATCH (a:Anomaly {id: $anomaly_id})-[r:HAS_FRAME]->(s:StackFrame)-[:IN_FILE]->(f:File)
    WHERE r.frame_order < $frame_limit
      AND s.resolution IN $valid_resolutions
    RETURN s.id AS frame_id,
           r.frame_order AS frame_order,
           s.symbol_name AS symbol_name,
           f.file_id AS file_id,
           f.path AS path,
           f.repo_ref AS repo_ref
    ORDER BY r.frame_order ASC
    """
    rows = client.execute_read(
        q,
        {
            "anomaly_id": anomaly_id,
            "frame_limit": K_frames,
            "valid_resolutions": list(VALID_RESOLUTIONS),
        },
    )
    traces = [r for r in rows if r.get("frame_id")]
    print(f"[RCA] Extracted traces: {len(traces)}")
    print(f"[RCA] Sample trace: {traces[:1]}")

    logger.debug(
        "candidate_generator.frames_fetched",
        extra={"anomaly_id": anomaly_id, "frame_count": len(rows)},
    )

    # Deduplicate by file_id; keep smallest frame_order per file; exclude vendor/stdlib
    by_file: dict[str, dict[str, Any]] = {}
    excluded_count = 0
    for r in rows:
        fid = r.get("file_id")
        path = r.get("path") or ""
        if not fid:
            continue
        if _is_excluded_path(path):
            excluded_count += 1
            logger.debug(
                "candidate_generator.path_excluded",
                extra={"anomaly_id": anomaly_id, "file_id": fid, "path": path},
            )
            continue
        order = r.get("frame_order", 999)
        if fid not in by_file or order < by_file[fid]["frame_order"]:
            by_file[fid] = {
                "file_id": fid,
                "path": path,
                "repo_ref": r.get("repo_ref") or "",
                "frame_id": r.get("frame_id"),
                "frame_order": order,
                "symbol_name": r.get("symbol_name"),
            }

    # Sort by frame_order, then path; cap at K_frames
    sorted_items = sorted(
        by_file.values(),
        key=lambda x: (x["frame_order"], x["path"] or ""),
    )[:K_frames]

    result: list[Candidate] = []
    signal_files = (signals or {}).get("files", []) if isinstance(signals, dict) else []

    # FILE-LEVEL from parsed log signals
    for file in signal_files:
        if not isinstance(file, str) or not file.strip():
            continue
        result.append(
            Candidate(
                file_id=file,
                representative_frame=RepresentativeFrame(
                    frame_id=f"signal::{file}",
                    frame_order=0,
                    symbol_name="signal_file",
                ),
                path=file,
                repo_ref="signals",
                type="file",
                value=file,
                score=0.8,
            )
        )

    # Existing trace-based logic when signal-derived files are not available.
    if not result:
        for item in sorted_items:
            frame_id = item.get("frame_id") or ""
            if not frame_id:
                continue
            rep = RepresentativeFrame(
                frame_id=frame_id,
                frame_order=item["frame_order"],
                symbol_name=item.get("symbol_name"),
            )
            result.append(
                Candidate(
                    file_id=item["file_id"],
                    representative_frame=rep,
                    path=item["path"],
                    repo_ref=item["repo_ref"],
                    type="file",
                    value=item["path"] or item["file_id"],
                    score=1.0,
                )
            )

    # SERVICE-LEVEL FALLBACK
    if not result and (signals or {}).get("service"):
        service = str((signals or {}).get("service"))
        result.append(
            Candidate(
                file_id=f"service::{service}",
                representative_frame=RepresentativeFrame(
                    frame_id=f"fallback::{service}",
                    frame_order=0,
                    symbol_name="service_fallback",
                ),
                path=f"service::{service}",
                repo_ref="fallback",
                type="service",
                value=service,
                reason="High frequency of errors and timeouts",
                score=0.6,
            )
        )

    # Absolute fallback to keep output non-empty even when service is missing.
    if not result:
        result.append(
            Candidate(
                file_id="service::unknown-service",
                representative_frame=RepresentativeFrame(
                    frame_id="fallback::unknown-service",
                    frame_order=0,
                    symbol_name="service_fallback",
                ),
                path="service::unknown-service",
                repo_ref="fallback",
                type="service",
                value="unknown-service",
                reason="High frequency of errors and timeouts",
                score=0.6,
            )
        )

    logger.info(
        "candidate_generator.complete",
        extra={
            "anomaly_id": anomaly_id,
            "candidate_count": len(result),
            "excluded_count": excluded_count,
            "file_ids": [item["file_id"] for item in sorted_items],
        },
    )
    print("----- CANDIDATES -----")
    print(
        [
            {
                "type": c.type,
                "value": c.value,
                "score": c.score,
                "reason": c.reason,
            }
            for c in result
        ]
    )

    return result
