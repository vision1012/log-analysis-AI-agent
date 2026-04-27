"""Anomaly read endpoint backed by Neo4j."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Query

from schemas.anomalies import AnomalyResponse
from services.anomalies_service import list_anomalies as list_anomalies_svc

router = APIRouter()


@router.get("/anomalies", response_model=List[AnomalyResponse])
async def list_anomalies(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[AnomalyResponse]:
    """List anomalies from graph storage."""
    return list_anomalies_svc(limit=limit, offset=offset)
