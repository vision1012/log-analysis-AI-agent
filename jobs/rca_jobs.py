"""
Celery background job entrypoints for RCA.
"""

from __future__ import annotations

import logging
import os
from typing import Any

# Optional Celery app. Set CELERY_BROKER_URL to enable.
try:
    from celery import Celery

    _celery = Celery(
        "rca_jobs",
        broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    )
except ImportError:
    _celery = None

from jobs.job_locking import acquire_lock, release_lock

logger = logging.getLogger(__name__)

# Transient errors: retry. Non-transient: fail immediately.
TRANSIENT_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


def _log_result(task_name: str, anomaly_id: str, result: dict[str, Any]) -> None:
    """Structured log for RCA job result."""
    logger.info(
        "rca_job_complete task=%s anomaly_id=%s status=%s run_id=%s attribution_count=%s",
        task_name,
        anomaly_id,
        result.get("status"),
        result.get("run_id"),
        result.get("attribution_count"),
    )


def _run_auto_with_lock(anomaly_id: str) -> dict[str, Any]:
    """Acquire lock, run auto RCA via service, release on success/failure."""
    from api.services.rca_service import trigger_auto_rca

    if not acquire_lock(anomaly_id, timeout_sec=0):
        return {
            "status": "rejected",
            "anomaly_id": anomaly_id,
            "reason": "Could not acquire lock; run already in progress",
        }
    try:
        return trigger_auto_rca(anomaly_id, _lock_held=True)
    finally:
        release_lock(anomaly_id)


def _run_manual_with_lock(
    anomaly_id: str,
    idempotency_key: str,
    force: bool = False,
) -> dict[str, Any]:
    """Acquire lock, run manual RCA via service, release on success/failure."""
    from api.services.rca_service import trigger_manual_rca

    if not acquire_lock(anomaly_id, timeout_sec=0):
        return {
            "status": "rejected",
            "anomaly_id": anomaly_id,
            "run_id": idempotency_key,
            "reason": "Could not acquire lock; run already in progress",
        }
    try:
        return trigger_manual_rca(anomaly_id, idempotency_key, force=force, _lock_held=True)
    finally:
        release_lock(anomaly_id)


if _celery is not None:

    @_celery.task(
        bind=True,
        autoretry_for=TRANSIENT_EXCEPTIONS,
        retry_backoff=True,
        retry_backoff_max=600,
        retry_jitter=True,
    )
    def run_auto_rca_job(self, anomaly_id: str) -> dict[str, Any]:
        """
        Run auto RCA for one anomaly.
        Retries only on transient errors (ConnectionError, TimeoutError, OSError).
        """
        logger.info("rca_job_start task=run_auto_rca_job anomaly_id=%s", anomaly_id)
        result = _run_auto_with_lock(anomaly_id)
        _log_result("run_auto_rca_job", anomaly_id, result)
        return result

    @_celery.task(
        bind=True,
        autoretry_for=TRANSIENT_EXCEPTIONS,
        retry_backoff=True,
        retry_backoff_max=600,
        retry_jitter=True,
    )
    def run_manual_rca_job(
        self,
        anomaly_id: str,
        idempotency_key: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Run manual RCA for one anomaly with idempotency key.
        Retries only on transient errors.
        """
        logger.info(
            "rca_job_start task=run_manual_rca_job anomaly_id=%s idempotency_key=%s",
            anomaly_id,
            idempotency_key,
        )
        result = _run_manual_with_lock(anomaly_id, idempotency_key, force)
        _log_result("run_manual_rca_job", anomaly_id, result)
        return result

else:
    run_auto_rca_job = None
    run_manual_rca_job = None
