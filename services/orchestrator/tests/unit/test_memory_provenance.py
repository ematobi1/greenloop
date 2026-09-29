from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.memory import provenance
from greenloop_contracts import (
    MemoryCategory,
    MemoryConfidence,
    MemoryOperation,
    MemorySource,
)

LATER = datetime(2099, 1, 1, tzinfo=UTC)


def test_supersede_links_to_the_original_and_keeps_owner_and_scope(make_record):
    original = make_record("v1")
    successor = provenance.supersede(original, "v2", "user-1")
    assert successor.record_id != original.record_id
    assert successor.record_id.startswith("mem-")
    assert successor.principal_id == original.principal_id
    assert successor.scope == original.scope
    assert successor.content == "v2"
    assert successor.provenance.operation is MemoryOperation.SUPERSEDE
    assert successor.provenance.supersedes == original.record_id
    assert successor.provenance.created_by == "user-1"
    assert successor.provenance.source is MemorySource.USER
    assert original.content == "v1"


def test_supersede_carries_fields_over_unless_changed(make_record):
    original = make_record("v1").model_copy(update={"tags": ("a",), "expires_at": LATER})
    kept = provenance.supersede(original, "v2", "user-1")
    assert (kept.category, kept.tags, kept.expires_at) == (original.category, ("a",), LATER)
    changed = provenance.supersede(
        original,
        "v2",
        "user-1",
        category=MemoryCategory.DECISION,
        confidence=MemoryConfidence.VERIFIED,
        tags=(),
        expires_at=None,
    )
    assert changed.category is MemoryCategory.DECISION
    assert changed.confidence is MemoryConfidence.VERIFIED
    assert changed.tags == ()
    assert changed.expires_at is None


def test_correct_forces_corrected_confidence(make_record):
    corrected = provenance.correct(make_record("wrong"), "right", "user-1", source_ref="review")
    assert corrected.confidence is MemoryConfidence.CORRECTED
    assert corrected.provenance.operation is MemoryOperation.CORRECT
    assert corrected.provenance.source_ref == "review"
    assert corrected.content == "right"


def test_tombstone_carries_no_content_tags_or_expiry(make_record):
    original = make_record("secret").model_copy(update={"tags": ("a",), "expires_at": LATER})
    tombstone = provenance.tombstone(original, "user-1")
    assert tombstone.content == ""
    assert tombstone.tags == ()
    assert tombstone.expires_at is None
    assert tombstone.provenance.operation is MemoryOperation.DELETE
    assert tombstone.provenance.supersedes == original.record_id


def test_blank_revision_content_is_rejected_by_the_contract(make_record):
    with pytest.raises(ValidationError, match="content is required"):
        provenance.supersede(make_record("v1"), "   ", "user-1")
