"""Service layer for anomaly read APIs."""

from __future__ import annotations

from typing import List

from db.neo4j.anomalies_repository import list_anomalies as list_anomalies_repo
from schemas.anomalies import AnomalyResponse


def list_anomalies(*, limit: int = 50, offset: int = 0) -> List[AnomalyResponse]:
    """
    List anomalies directly from Neo4j (no mock or hardcoded payloads).
    """
    rows = list_anomalies_repo(limit=limit, offset=offset)
    return [AnomalyResponse.model_validate(row) for row in rows]
