"""Event: a timestamped occurrence published inside GreenLoop."""

from typing import Annotated

from pydantic import Field, JsonValue, StringConstraints

from greenloop_contracts.base import AgentIdentifier, ContractModel, Identifier, Timestamp

EventType = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=100),
]
"""Dotted lowercase name, at least two segments, such as task.created."""


class Event(ContractModel):
    schema_version = "2"

    event_id: Identifier
    event_type: EventType
    source: Identifier
    correlation_id: Identifier
    principal_id: Identifier | None = None
    task_id: Identifier | None = None
    agent_id: AgentIdentifier | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    occurred_at: Timestamp
