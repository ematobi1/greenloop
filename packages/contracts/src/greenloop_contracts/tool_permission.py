"""ToolPermission: a request to run one tool operation, evaluated by policy.

Its canonical form and SHA256 (`operation.py`) are what an approval binds to.

The consequence class decides the path: reads may go direct, anything that
writes, sends, deletes or spends must go through the broker.
"""

import json
from enum import StrEnum

from pydantic import Field, JsonValue, field_validator

from greenloop_contracts.base import ContractModel, Identifier


class ToolConsequence(StrEnum):
    READ = "read"
    WRITE = "write"
    SEND = "send"
    DELETE = "delete"
    SPEND = "spend"


MAX_ARGUMENT_BYTES = 65_536


class ToolPermission(ContractModel):
    schema_version = "2"

    principal_id: Identifier
    agent_id: Identifier | None = None
    tool: Identifier
    operation: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    consequence: ToolConsequence

    @field_validator("arguments")
    @classmethod
    def _strict_bounded_json(cls, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Arguments are what an approval binds to, so they must hash: strict JSON (no
        NaN or Infinity) and at most MAX_ARGUMENT_BYTES as UTF-8."""
        try:
            text = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except ValueError:
            raise ValueError("arguments must be JSON without NaN or Infinity") from None
        if len(text.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise ValueError(f"arguments must be at most {MAX_ARGUMENT_BYTES} bytes as JSON")
        return arguments

    @property
    def is_consequential(self) -> bool:
        return self.consequence is not ToolConsequence.READ
