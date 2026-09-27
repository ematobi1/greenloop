import pytest

from app.permissions.policy import PolicyDecision, evaluate
from greenloop_contracts import ToolPermission


@pytest.mark.parametrize("consequence", ["read", "write", "send", "delete", "spend"])
def test_policy_denies_everything_until_phase_3(consequence):
    permission = ToolPermission(
        principal_id="user-1", tool="github", operation="create_issue", consequence=consequence
    )
    assert evaluate(permission) is PolicyDecision.DENY
