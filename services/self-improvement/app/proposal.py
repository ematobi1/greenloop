"""Proposal: a suggested change to GreenLoop itself, with the evidence behind it."""

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=4000)
    diff: str = Field(min_length=1, max_length=200_000)
    created_by: str = Field(min_length=1, max_length=128)
    evidence_ids: tuple[str, ...] = ()
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
