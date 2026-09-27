"""Base model and shared field types for every GreenLoop contract.

Contracts are immutable and reject unknown fields, so a producer and consumer
cannot silently drift apart. Timestamps must be timezone-aware.
"""

from datetime import UTC, datetime
from typing import Annotated, ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$"),
]
"""Opaque string id: 1-128 chars, starts alphanumeric, then letters, digits, . _ : -"""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""Lowercase hex SHA256 digest."""

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=4000)]

Timestamp = Annotated[AwareDatetime, Field(default_factory=lambda: datetime.now(UTC))]


class ContractModel(BaseModel):
    """Base for all contracts: frozen, strict about unknown fields, versioned."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    schema_version: ClassVar[str] = "1"
