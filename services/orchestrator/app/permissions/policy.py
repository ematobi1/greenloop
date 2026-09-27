"""The single permission model: decide allow, deny or require approval for a ToolPermission.

Until the policy engine lands in phase 3, every request is denied. Deny is the
safe default; the broker enforces the same rule independently.
"""

from enum import StrEnum

from greenloop_contracts import ToolPermission


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


def evaluate(permission: ToolPermission) -> PolicyDecision:
    # TODO(phase-3): load rules and match on principal, agent, tool, operation, consequence.
    return PolicyDecision.DENY
