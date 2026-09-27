from dataclasses import replace

import pytest

from app.ledger import GENESIS, InMemoryLedger, verify_chain
from greenloop_contracts import AuditRecord


def audit(index: int, outcome: str = "denied") -> AuditRecord:
    return AuditRecord(
        audit_id=f"audit-{index}",
        principal_id="user-1",
        actor="broker",
        action="github.create_issue",
        resource_type="repository",
        resource_id="greenloop",
        outcome=outcome,
        correlation_id=f"corr-{index}",
        occurred_at="2026-09-27T12:00:00Z",
    )


@pytest.fixture
def ledger() -> InMemoryLedger:
    ledger = InMemoryLedger()
    for index in range(3):
        ledger.append(audit(index))
    return ledger


def test_empty_ledger_starts_at_genesis():
    assert InMemoryLedger().head == GENESIS
    assert InMemoryLedger().verify()


def test_entries_chain_to_previous_hash(ledger):
    entries = ledger.entries()
    assert entries[0].previous_hash == GENESIS
    assert entries[1].previous_hash == entries[0].entry_hash
    assert ledger.head == entries[-1].entry_hash
    assert ledger.verify()


def test_edited_record_breaks_chain(ledger):
    entries = list(ledger.entries())
    entries[1] = replace(entries[1], record=audit(1, outcome="executed"))
    assert not verify_chain(entries)


def test_removed_entry_breaks_chain(ledger):
    entries = list(ledger.entries())
    del entries[1]
    assert not verify_chain(entries)


def test_reordered_entries_break_chain(ledger):
    entries = list(ledger.entries())
    entries[0], entries[1] = entries[1], entries[0]
    assert not verify_chain(entries)


def test_entries_view_is_read_only(ledger):
    assert isinstance(ledger.entries(), tuple)
