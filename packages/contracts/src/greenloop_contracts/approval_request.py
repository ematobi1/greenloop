"""Requests the orchestrator sends to the broker's approvals API (ADR 0009).

The broker never accepts an Approval as input (rule 7): creating one sends the
operation, deciding one sends the approval_id (in the path) and the answer. Both name
the actor, which the orchestrator fills only from its authenticated Principal, never
from user request data. The broker trusts these fields because the call carries its
service token; a signed per-user assertion is a later hardening item.

`in_dispatch` and `kind` have no defaults: the caller must state them, so a forgotten
field fails validation instead of quietly meaning "a human, outside a dispatch".
"""

from enum import StrEnum

from pydantic import StrictBool, model_validator

from greenloop_contracts.base import ContractModel, Identifier
from greenloop_contracts.tool_permission import ToolPermission


class ActorKind(StrEnum):
    USER = "user"
    SYSTEM = "system"


class ApprovalActor(ContractModel):
    schema_version = "1"

    principal_id: Identifier
    kind: ActorKind
    in_dispatch: StrictBool

    @property
    def may_decide(self) -> bool:
        """Only a human user, acting directly, decides an approval (rule 6)."""
        return self.kind is ActorKind.USER and not self.in_dispatch


class ApprovalCreateRequest(ContractModel):
    schema_version = "1"

    operation: ToolPermission
    actor: ApprovalActor

    @model_validator(mode="after")
    def _actor_owns_the_operation(self) -> "ApprovalCreateRequest":
        if self.actor.principal_id != self.operation.principal_id:
            raise ValueError("the actor must be the principal the operation belongs to")
        return self


class ApprovalDecisionRequest(ContractModel):
    schema_version = "1"

    approved: StrictBool
    actor: ApprovalActor
