"""Agent: how a specialized agent registers with the orchestrator.

`domain` is a closed set on purpose: a new domain is a reviewed contract change,
not a value an agent can invent.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from greenloop_contracts.base import (
    AgentIdentifier,
    ContractModel,
    Identifier,
    LongText,
    ShortText,
    Timestamp,
)


class AgentDomain(StrEnum):
    SOFTWARE_ENGINEERING = "software-engineering"
    DEVOPS_INFRASTRUCTURE = "devops-infrastructure"
    CYBERSECURITY = "cybersecurity"
    RESEARCH = "research"
    BUSINESS_OPERATIONS = "business-operations"
    PERSONAL_PRODUCTIVITY = "personal-productivity"
    OTHER = "other"


class AgentStatus(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    DISABLED = "disabled"


class Agent(ContractModel):
    schema_version = "2"

    agent_id: AgentIdentifier
    name: ShortText
    domain: AgentDomain
    version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    description: LongText = ""
    capabilities: tuple[Identifier, ...] = Field(min_length=1)
    allowed_tools: tuple[Identifier, ...] = ()
    status: AgentStatus = AgentStatus.REGISTERED
    created_at: Timestamp
    updated_at: Timestamp

    @field_validator("capabilities", "allowed_tools")
    @classmethod
    def _unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("entries must be unique")
        return values

    @model_validator(mode="after")
    def _updated_not_before_created(self) -> "Agent":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        return self
