"""Dispatch permission: may this principal run this agent? Part of the one permission
model, beside policy and approvals.

An agent that reaches no model and no tool is open to every authenticated principal.
An agent with model or tool access may be dispatched by system principals only, until
a grant API exists (Terry, 2026-10-02). Users will then need a matching ToolGrant.
"""

from app.core.auth import Principal
from greenloop_contracts import Agent


def may_dispatch(principal: Principal, agent: Agent) -> bool:
    if not agent.model_access and not agent.allowed_tools:
        return True
    return principal.is_system
