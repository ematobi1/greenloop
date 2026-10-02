"""Dispatch permission: may this principal run this agent? Part of the one permission
model, beside policy and approvals.

`needs_dispatch_permission` is the one definition of which agents need the check: an
agent that can reach a model or a tool. An agent with neither is open to every
authenticated principal. An agent with either may be dispatched by system principals
only, until a grant API exists (Terry, 2026-10-02). Which grant a user will need for
a model-only agent is still open: ToolGrant covers tools.
"""

from typing import TYPE_CHECKING

from greenloop_contracts import Agent

if TYPE_CHECKING:
    from app.core.auth import Principal


def needs_dispatch_permission(agent: Agent) -> bool:
    return agent.model_access or bool(agent.allowed_tools)


def may_dispatch(principal: "Principal", agent: Agent) -> bool:
    if not needs_dispatch_permission(agent):
        return True
    return principal.is_system
