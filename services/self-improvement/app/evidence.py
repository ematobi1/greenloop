"""Evidence: measurements that justify a proposal (eval scores, error rates, traces)."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=2000)
    data: dict[str, JsonValue] = Field(default_factory=dict)
