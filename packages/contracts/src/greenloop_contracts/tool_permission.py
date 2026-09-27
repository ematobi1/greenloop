"""ToolPermission: a request to run one tool operation, evaluated by policy.

The consequence class decides the path: reads may go direct, anything that
writes, sends, deletes or spends must go through the broker.
"""

from enum import StrEnum

from pydantic import Field, JsonValue

from greenloop_contracts.base import ContractModel, Identifier


class ToolConsequence(StrEnum):
    READ = "read"
    WRITE = "write"
    SEND = "send"
    DELETE = "delete"
    SPEND = "spend"


class ToolPermission(ContractModel):
    principal_id: Identifier
    agent_id: Identifier | None = None
    tool: Identifier
    operation: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    consequence: ToolConsequence

    @property
    def is_consequential(self) -> bool:
        return self.consequence is not ToolConsequence.READ
