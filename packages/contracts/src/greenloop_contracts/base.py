"""Base model and shared field types for every GreenLoop contract.

Contracts are immutable and reject unknown fields, so a producer and consumer
cannot silently drift apart. Timestamps must be timezone-aware and are
normalized to UTC, so they serialize with a trailing Z.
"""

from datetime import UTC, datetime
from typing import Annotated, ClassVar

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$"),
]
"""Opaque string id: 1-128 chars, starts alphanumeric, then letters, digits, . _ : -"""

AgentIdentifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]
"""Agent id: 1-100 chars of lowercase letters, digits and hyphens."""

ErrorCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)]
"""Machine-readable error code in UPPER_SNAKE_CASE (digits allowed after the first letter,
e.g. HTTP_429), shared with the API error envelope."""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""Lowercase hex SHA256 digest."""

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=4000)]
SafeMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
"""Human-readable message that is safe to show a user."""


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
Timestamp = Annotated[UtcDatetime, Field(default_factory=lambda: datetime.now(UTC))]


class ContractModel(BaseModel):
    """Base for all contracts: frozen, strict about unknown fields, versioned."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    schema_version: ClassVar[str] = "1"
