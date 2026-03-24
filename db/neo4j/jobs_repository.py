"""
CRUD and lifecycle helpers for ``Job`` nodes (Neo4j).

User data is not stored here; only ``triggered_by_user_id`` on the job.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from neo4j import Driver

from db.neo4j.connection import get_driver


def _to_plain(value: Any) -> Any:
    """Normalize Neo4j temporal types for plain dicts / JSON."""
    if value is None:
        return None
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        return to_native()
    return value


def _node_to_dict(node: Any) -> dict[str, Any]:
    return {key: _to_plain(node[key]) for key in node.keys()}


def _record_job(record: Any) -> dict[str, Any]:
    return _node_to_dict(record["j"])


def create_job(job_data: Mapping[str, Any], driver: Optional[Driver] = None) -> dict[str, Any]:
    """
    Create a ``Job`` with ``status=queued`` and ``created_at`` set (UTC).

    Required in ``job_data``: ``job_id``, ``job_type``.
    """
    drv = driver or get_driver()
    job_id = job_data["job_id"]
    job_type = job_data["job_type"]
    now = datetime.now(timezone.utc)
    props = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "anomaly_id": job_data.get("anomaly_id"),
        "run_id": job_data.get("run_id"),
        "triggered_by_user_id": job_data.get("triggered_by_user_id"),
        "trigger_source": job_data.get("trigger_source"),
        "error_message": job_data.get("error_message"),
    }
    query = """
    CREATE (j:Job {
      job_id: $job_id,
      job_type: $job_type,
      status: $status,
      created_at: $created_at,
      started_at: $started_at,
      completed_at: $completed_at,
      anomaly_id: $anomaly_id,
      run_id: $run_id,
      triggered_by_user_id: $triggered_by_user_id,
      trigger_source: $trigger_source,
      error_message: $error_message
    })
    RETURN j
    """
    with drv.session() as session:
        record = session.run(query, props).single()
        if record is None:
            raise RuntimeError("Failed to create Job")
        return _record_job(record)


def get_job(job_id: str, driver: Optional[Driver] = None) -> Optional[dict[str, Any]]:
    drv = driver or get_driver()
    query = """
    MATCH (j:Job {job_id: $job_id})
    RETURN j
    """
    with drv.session() as session:
        record = session.run(query, {"job_id": job_id}).single()
        if record is None:
            return None
        return _record_job(record)


def list_jobs(limit: int = 50, offset: int = 0, driver: Optional[Driver] = None) -> list[dict[str, Any]]:
    drv = driver or get_driver()
    query = """
    MATCH (j:Job)
    RETURN j
    ORDER BY j.created_at DESC
    SKIP $offset
    LIMIT $limit
    """
    with drv.session() as session:
        result = session.run(query, {"limit": limit, "offset": offset})
        return [_record_job(r) for r in result]


def update_job_status(
    job_id: str,
    status: str,
    error_message: Optional[str] = None,
    driver: Optional[Driver] = None,
) -> Optional[dict[str, Any]]:
    drv = driver or get_driver()
    if error_message is not None:
        query = """
        MATCH (j:Job {job_id: $job_id})
        SET j.status = $status, j.error_message = $error_message
        RETURN j
        """
        params: dict[str, Any] = {"job_id": job_id, "status": status, "error_message": error_message}
    else:
        query = """
        MATCH (j:Job {job_id: $job_id})
        SET j.status = $status
        RETURN j
        """
        params = {"job_id": job_id, "status": status}
    with drv.session() as session:
        record = session.run(query, params).single()
        if record is None:
            return None
        return _record_job(record)


def mark_job_running(
    job_id: str,
    started_at: datetime,
    driver: Optional[Driver] = None,
) -> Optional[dict[str, Any]]:
    drv = driver or get_driver()
    query = """
    MATCH (j:Job {job_id: $job_id})
    SET j.status = 'running', j.started_at = $started_at
    RETURN j
    """
    with drv.session() as session:
        record = session.run(query, {"job_id": job_id, "started_at": started_at}).single()
        if record is None:
            return None
        return _record_job(record)


def mark_job_completed(
    job_id: str,
    completed_at: datetime,
    driver: Optional[Driver] = None,
) -> Optional[dict[str, Any]]:
    drv = driver or get_driver()
    query = """
    MATCH (j:Job {job_id: $job_id})
    SET j.status = 'completed', j.completed_at = $completed_at
    RETURN j
    """
    with drv.session() as session:
        record = session.run(query, {"job_id": job_id, "completed_at": completed_at}).single()
        if record is None:
            return None
        return _record_job(record)


def mark_job_failed(
    job_id: str,
    completed_at: datetime,
    error_message: str,
    driver: Optional[Driver] = None,
) -> Optional[dict[str, Any]]:
    drv = driver or get_driver()
    query = """
    MATCH (j:Job {job_id: $job_id})
    SET j.status = 'failed', j.completed_at = $completed_at, j.error_message = $error_message
    RETURN j
    """
    with drv.session() as session:
        record = session.run(
            query,
            {"job_id": job_id, "completed_at": completed_at, "error_message": error_message},
        ).single()
        if record is None:
            return None
        return _record_job(record)
