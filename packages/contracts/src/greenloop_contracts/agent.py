"""Agent: a registered unit that carries out plan steps."""

from enum import StrEnum

from pydantic import field_validator

from greenloop_contracts.base import ContractModel, Identifier, LongText, ShortText


class AgentStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Agent(ContractModel):
    agent_id: Identifier
    name: ShortText
    description: LongText = ""
    capabilities: tuple[Identifier, ...] = ()
    allowed_tools: tuple[Identifier, ...] = ()
    status: AgentStatus = AgentStatus.ACTIVE

    @field_validator("capabilities", "allowed_tools")
    @classmethod
    def _unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("entries must be unique")
        return values
