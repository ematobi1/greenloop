"""Agents: read-only view of the agent registry.

TODO(phase-4): serve registered agents from app/agents/registry.py.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents() -> None:
    raise not_implemented("Agent listing", phase=4)


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> None:
    raise not_implemented("Agent lookup", phase=4)
