from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

ANOMALY_STORE: List[dict] = []


class Anomaly(BaseModel):
    anomaly_id: str
    service: str
    severity: str
    summary: str
    timestamp: str


@router.post("/api/v1/anomalies")
def create_anomaly(anomaly: Anomaly):
    ANOMALY_STORE.append(anomaly.dict())
    return {"message": "Anomaly created", "data": anomaly}


@router.get("/api/v1/anomalies")
def get_anomalies():
    return ANOMALY_STORE
