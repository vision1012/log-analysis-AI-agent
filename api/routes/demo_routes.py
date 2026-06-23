"""Conference demo mode API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.deps.auth import get_current_user
from demo.demo_service import launch_scenario, list_scenarios, load_scenario
from schemas.users import UserResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/demo/scenarios")
async def list_demo_scenarios_endpoint() -> dict[str, object]:
    """List all pre-built conference demo scenarios."""
    scenarios = list_scenarios()
    return {"scenarios": [scenario.model_dump() for scenario in scenarios]}


@router.get("/demo/scenarios/{scenario_id}")
async def get_demo_scenario_endpoint(
    scenario_id: str = Path(..., min_length=1, description="Demo scenario id"),
) -> dict[str, object]:
    """Return one demo scenario with timeline, graph, and similar-incident preview data."""
    try:
        scenario = load_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "demo_scenario_not_found", "message": str(exc)},
        ) from exc
    return {"scenario": scenario.model_dump()}


@router.post("/demo/scenarios/{scenario_id}/launch")
async def launch_demo_scenario_endpoint(
    scenario_id: str = Path(..., min_length=1, description="Demo scenario id"),
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, object]:
    """Launch a demo scenario as a full investigation workspace."""
    try:
        result = launch_scenario(scenario_id, user_id=current_user.user_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "demo_scenario_not_found", "message": str(exc)},
        ) from exc
    return {"launch": result.model_dump()}
