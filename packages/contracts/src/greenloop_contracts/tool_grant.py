"""ToolGrant: a standing permission the owner gives one agent to use listed actions of one tool.

A grant is not a credential; every call still goes through policy, approval when
required, the broker and audit. `granted_by` is fixed to "owner": this contract
has no way to represent an agent granting itself or another agent anything.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from greenloop_contracts.base import (
    AgentIdentifier,
    ContractModel,
    Identifier,
    Timestamp,
    UtcDatetime,
)
from greenloop_contracts.tool_permission import ToolPermission


class ToolGrant(ContractModel):
    grant_id: Identifier
    principal_id: Identifier
    agent_id: AgentIdentifier
    tool: Identifier
    actions: tuple[Identifier, ...] = Field(min_length=1)
    granted_by: Literal["owner"]
    granted_at: Timestamp
    expires_at: UtcDatetime | None = None

    @field_validator("actions")
    @classmethod
    def _unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("actions must be unique")
        return values

    @model_validator(mode="after")
    def _expiry_after_grant(self) -> "ToolGrant":
        if self.expires_at is not None and self.expires_at <= self.granted_at:
            raise ValueError("expires_at must be after granted_at")
        return self

    def is_active(self, at: datetime) -> bool:
        return self.expires_at is None or at < self.expires_at

    def covers(self, permission: ToolPermission, at: datetime) -> bool:
        return (
            self.is_active(at)
            and permission.principal_id == self.principal_id
            and permission.agent_id == self.agent_id
            and permission.tool == self.tool
            and permission.operation in self.actions
        )
