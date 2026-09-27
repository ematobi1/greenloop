"""Plans: drafted sequences of tasks the user can review before anything runs.

TODO(phase-2): draft plans from the planner; TODO(phase-4): execute approved plans.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("", status_code=201)
async def create_plan() -> None:
    raise not_implemented("Plan drafting", phase=2)


@router.get("/{plan_id}")
async def get_plan(plan_id: str) -> None:
    raise not_implemented("Plan lookup", phase=2)
