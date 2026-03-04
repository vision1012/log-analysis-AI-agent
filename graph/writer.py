"""
Graph writer for RCA entities and edges.

Idempotent upserts and links. Safe for retries. Supports per-anomaly atomic transactions.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

from graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# Type for atomic batch operations: (query, params)
_Op = Tuple[str, dict[str, Any]]


class GraphWriteError(Exception):
    """Raised when a graph write operation fails."""

    def __init__(self, message: str, entity: Optional[str] = None, entity_id: Optional[str] = None):
        super().__init__(message)
        self.entity = entity
        self.entity_id = entity_id


class NodeNotFoundError(GraphWriteError):
    """Raised when a required node is not found for a link operation."""


def _log_upsert(entity: str, id_val: str, created: bool) -> None:
    logger.info("graph.upsert entity=%s id=%s created=%s", entity, id_val, created)


def _log_link(rel: str, from_id: str, to_id: str) -> None:
    logger.info("graph.link relationship=%s from=%s to=%s", rel, from_id, to_id)


class GraphWriter:
    """Idempotent graph writer. MERGE-based upserts; no duplicates on retry."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    def _run_or_batch(self, op: _Op, batch: Optional[List[_Op]] = None) -> None:
        if batch is not None:
            batch.append(op)
        else:
            self._client.execute_write(op[0], op[1])

    def upsert_anomaly(
        self,
        anomaly_id: str,
        timestamp: str,
        *,
        trace_ref: Optional[str] = None,
        score: Optional[float] = None,
        window_id: Optional[str] = None,
        _batch: Optional[List[_Op]] = None,
        **props: Any,
    ) -> None:
        """Upsert Anomaly node. MERGE on id. Pass _batch for atomic transaction."""
        q = """
        MERGE (a:Anomaly {id: $id})
        ON CREATE SET a.timestamp = $timestamp, a.trace_ref = $trace_ref,
                      a.score = $score, a.window_id = $window_id
        ON MATCH SET a.timestamp = $timestamp,
                     a.trace_ref = COALESCE($trace_ref, a.trace_ref),
                     a.score = COALESCE($score, a.score),
                     a.window_id = COALESCE($window_id, a.window_id)
        """
        params: dict[str, Any] = {
            "id": anomaly_id,
            "timestamp": timestamp,
            "trace_ref": trace_ref,
            "score": score,
            "window_id": window_id,
        }
        params.update(props)
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_upsert("Anomaly", anomaly_id, True)

    def upsert_stackframe(
        self,
        stackframe_id: str,
        trace_ref: str,
        *,
        symbol_name: Optional[str] = None,
        frame_order: Optional[int] = None,
        resolution: str = "resolved",
        _batch: Optional[List[_Op]] = None,
        **props: Any,
    ) -> None:
        """Upsert StackFrame node. MERGE on id. Pass _batch for atomic transaction."""
        q = """
        MERGE (s:StackFrame {id: $id})
        ON CREATE SET s.trace_ref = $trace_ref, s.symbol_name = $symbol_name,
                      s.frame_order = $frame_order, s.resolution = $resolution
        ON MATCH SET s.trace_ref = $trace_ref,
                     s.symbol_name = COALESCE($symbol_name, s.symbol_name),
                     s.frame_order = COALESCE($frame_order, s.frame_order),
                     s.resolution = COALESCE($resolution, s.resolution)
        """
        params: dict[str, Any] = {
            "id": stackframe_id,
            "trace_ref": trace_ref,
            "symbol_name": symbol_name,
            "frame_order": frame_order,
            "resolution": resolution,
        }
        params.update(props)
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_upsert("StackFrame", stackframe_id, True)

    def upsert_file(
        self,
        path: str,
        repo_ref: str,
        *,
        file_id: Optional[str] = None,
        _batch: Optional[List[_Op]] = None,
        **props: Any,
    ) -> None:
        """Upsert File node. MERGE on (path, repo_ref). Sets id on create. Pass _batch for atomic."""
        fid = file_id or f"{repo_ref}:{path}"
        q = """
        MERGE (f:File {path: $path, repo_ref: $repo_ref})
        ON CREATE SET f.id = $file_id
        ON MATCH SET f.id = COALESCE($file_id, f.id)
        """
        params: dict[str, Any] = {"path": path, "repo_ref": repo_ref, "file_id": fid}
        params.update(props)
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_upsert("File", fid, True)

    def upsert_commit(
        self,
        sha: str,
        repo_ref: str,
        timestamp: str,
        *,
        _batch: Optional[List[_Op]] = None,
        **props: Any,
    ) -> None:
        """Upsert Commit node. MERGE on (sha, repo_ref). Pass _batch for atomic transaction."""
        q = """
        MERGE (c:Commit {sha: $sha, repo_ref: $repo_ref})
        ON CREATE SET c.timestamp = $timestamp
        ON MATCH SET c.timestamp = $timestamp
        """
        params: dict[str, Any] = {"sha": sha, "repo_ref": repo_ref, "timestamp": timestamp}
        params.update(props)
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_upsert("Commit", sha, True)

    def upsert_deployment(
        self,
        deployment_id: str,
        timestamp: str,
        *,
        service_ref: Optional[str] = None,
        _batch: Optional[List[_Op]] = None,
        **props: Any,
    ) -> None:
        """Upsert Deployment node. MERGE on id. Pass _batch for atomic transaction."""
        q = """
        MERGE (d:Deployment {id: $id})
        ON CREATE SET d.timestamp = $timestamp, d.service_ref = $service_ref
        ON MATCH SET d.timestamp = $timestamp,
                     d.service_ref = COALESCE($service_ref, d.service_ref)
        """
        params: dict[str, Any] = {
            "id": deployment_id,
            "timestamp": timestamp,
            "service_ref": service_ref,
        }
        params.update(props)
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_upsert("Deployment", deployment_id, True)

    def link_has_frame(
        self,
        anomaly_id: str,
        stackframe_id: str,
        frame_order: int,
        *,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """Create HAS_FRAME edge. MERGE on (Anomaly, StackFrame); idempotent. Pass _batch for atomic."""
        q = """
        MERGE (a:Anomaly {id: $anomaly_id})
        MERGE (s:StackFrame {id: $stackframe_id})
        MERGE (a)-[r:HAS_FRAME]->(s)
        ON CREATE SET r.frame_order = $frame_order
        ON MATCH SET r.frame_order = $frame_order
        """
        params = {"anomaly_id": anomaly_id, "stackframe_id": stackframe_id, "frame_order": frame_order}
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_link("HAS_FRAME", anomaly_id, stackframe_id)

    def link_in_file(
        self,
        stackframe_id: str,
        file_id: str,
        *,
        resolution: Optional[str] = None,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """
        Create IN_FILE edge. MERGE on (StackFrame, File); idempotent.
        Optional: resolution, source, confidence (edge properties). Pass _batch for atomic.
        """
        q = """
        MATCH (s:StackFrame {id: $stackframe_id})
        MATCH (f:File) WHERE f.id = $file_id
        MERGE (s)-[r:IN_FILE]->(f)
        ON CREATE SET r.resolution = $resolution, r.source = $source, r.confidence = $confidence
        ON MATCH SET r.resolution = COALESCE($resolution, r.resolution),
                     r.source = COALESCE($source, r.source),
                     r.confidence = COALESCE($confidence, r.confidence)
        """
        params = {
            "stackframe_id": stackframe_id,
            "file_id": file_id,
            "resolution": resolution,
            "source": source,
            "confidence": confidence,
        }
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_link("IN_FILE", stackframe_id, file_id)

    def link_touched(
        self,
        commit_sha: str,
        repo_ref: str,
        file_id: str,
        *,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """
        Create TOUCHED edge. MERGE on (Commit, File); idempotent.
        File matched by id (must exist from upsert_file). Pass _batch for atomic.
        """
        q = """
        MATCH (c:Commit {sha: $commit_sha, repo_ref: $repo_ref})
        MATCH (f:File) WHERE f.id = $file_id
        WITH c, f LIMIT 1
        MERGE (c)-[:TOUCHED]->(f)
        """
        params = {"commit_sha": commit_sha, "repo_ref": repo_ref, "file_id": file_id}
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_link("TOUCHED", commit_sha, file_id)

    def link_deployed_commit(
        self,
        deployment_id: str,
        commit_sha: str,
        repo_ref: str,
        *,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """Create DEPLOYED_COMMIT edge. MERGE on (Deployment, Commit); idempotent. Pass _batch for atomic."""
        q = """
        MERGE (d:Deployment {id: $deployment_id})
        MERGE (c:Commit {sha: $commit_sha, repo_ref: $repo_ref})
        MERGE (d)-[:DEPLOYED_COMMIT]->(c)
        """
        params = {"deployment_id": deployment_id, "commit_sha": commit_sha, "repo_ref": repo_ref}
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_link("DEPLOYED_COMMIT", deployment_id, commit_sha)

    def write_rca_attributed(
        self,
        anomaly_id: str,
        frame_id: str,
        run_id: str,
        method: str,
        confidence: float,
        status: str,
        evidence_ref: str,
        attributed_at: str,
        *,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """Create RCA_ATTRIBUTED edge. Use with _batch for per-anomaly atomic transaction."""
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})
        MATCH (s:StackFrame {id: $frame_id})
        CREATE (a)-[:RCA_ATTRIBUTED {
            run_id: $run_id, method: $method, confidence: $confidence,
            status: $status, evidence_ref: $evidence_ref, attributed_at: $attributed_at
        }]->(s)
        """
        params = {
            "anomaly_id": anomaly_id,
            "frame_id": frame_id,
            "run_id": run_id,
            "method": method,
            "confidence": confidence,
            "status": status,
            "evidence_ref": evidence_ref,
            "attributed_at": attributed_at,
        }
        self._run_or_batch((q, params), _batch)
        if _batch is None:
            _log_link("RCA_ATTRIBUTED", anomaly_id, frame_id)

    def supersede_prior_attributions(
        self,
        anomaly_id: str,
        run_id: str,
        *,
        _batch: Optional[List[_Op]] = None,
    ) -> None:
        """
        Set prior candidate/accepted to superseded before writing new attributions.
        Pass _batch for atomic transaction.
        """
        q = """
        MATCH (a:Anomaly {id: $anomaly_id})-[r:RCA_ATTRIBUTED]->()
        WHERE r.status IN ['candidate', 'accepted'] AND r.run_id <> $run_id
        SET r.status = 'superseded'
        """
        params = {"anomaly_id": anomaly_id, "run_id": run_id}
        self._run_or_batch((q, params), _batch)

    def write_atomic(self, operations: list[tuple[str, dict[str, Any]]]) -> None:
        """
        Run multiple write operations in one atomic transaction.
        For per-anomaly atomic writes, pass _batch=[] to each method, then write_atomic(batch).

        Example:
            batch = []
            writer.supersede_prior_attributions(anomaly_id, run_id, _batch=batch)
            writer.write_rca_attributed(..., _batch=batch)
            writer.write_atomic(batch)
        """
        self._client.execute_write_tx(operations)
