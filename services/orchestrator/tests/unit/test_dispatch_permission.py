import pytest

from app.agents.reference import EchoReferenceAgent
from app.core.auth import Principal
from app.db.models import PrincipalRole
from app.permissions.dispatch import may_dispatch

USER = Principal(principal_id="user-1", display_name="User")
SYSTEM = Principal(principal_id="svc-1", display_name="Service", role=PrincipalRole.SYSTEM)
OPEN = EchoReferenceAgent.descriptor


@pytest.mark.parametrize(
    "access",
    [
        {"model_access": True},
        {"allowed_tools": ("web.fetch",)},
        {"model_access": True, "allowed_tools": ("x",)},
    ],
)
def test_only_system_principals_may_dispatch_agents_with_model_or_tool_access(access):
    agent = OPEN.model_copy(update=access)
    assert may_dispatch(SYSTEM, agent)
    assert not may_dispatch(USER, agent)


def test_anyone_may_dispatch_an_agent_with_no_model_or_tool_access():
    assert may_dispatch(USER, OPEN)
    assert may_dispatch(SYSTEM, OPEN)
