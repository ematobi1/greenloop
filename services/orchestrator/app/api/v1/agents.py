"""Agents: read-only view of the agent registry (app/agents/registry.py)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel

from app.agents.registry import AgentRegistry, UnknownAgentError
from app.api.v1.pagination import Limit, Offset, PageMeta
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from greenloop_contracts import Agent, AgentDomain, AgentStatus

router = APIRouter(prefix="/agents", tags=["agents"])


def get_agent_registry(request: Request) -> AgentRegistry:
    return request.app.state.agent_registry


Registry = Annotated[AgentRegistry, Depends(get_agent_registry)]
AgentId = Annotated[str, Path(max_length=100)]


class AgentPage(BaseModel):
    data: list[Agent]
    meta: PageMeta


def agent_not_found() -> ApiError:
    return ApiError(404, "AGENT_NOT_FOUND", "Agent not found.")


@router.get("")
def list_agents(
    _principal: CurrentPrincipal,
    registry: Registry,
    limit: Limit = 50,
    offset: Offset = 0,
    domain: AgentDomain | None = None,
    status: AgentStatus | None = None,
) -> AgentPage:
    agents = registry.list(domain=domain, status=status)
    return AgentPage(
        data=agents[offset : offset + limit],
        meta=PageMeta(total=len(agents), limit=limit, offset=offset),
    )


@router.get("/{agent_id}")
def get_agent(agent_id: AgentId, _principal: CurrentPrincipal, registry: Registry) -> Agent:
    try:
        return registry.get(agent_id).descriptor
    except UnknownAgentError:
        raise agent_not_found() from None
