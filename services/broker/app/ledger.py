"""Append-only audit ledger with a SHA256 hash chain.

Each entry stores the hash of the previous entry, so editing, removing or
reordering any past entry breaks `verify()`.

TODO(phase-3): persist to Postgres (insert-only role) and periodically anchor the head hash.
"""

import hashlib
import json
from dataclasses import dataclass

from greenloop_contracts import AuditRecord

GENESIS = "0" * 64


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    record: AuditRecord
    previous_hash: str
    entry_hash: str


def _entry_hash(sequence: int, record: AuditRecord, previous_hash: str) -> str:
    body = json.dumps(
        {"sequence": sequence, "previous": previous_hash, "record": record.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class InMemoryLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    @property
    def head(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS

    def append(self, record: AuditRecord) -> LedgerEntry:
        sequence = len(self._entries)
        entry = LedgerEntry(sequence, record, self.head, _entry_hash(sequence, record, self.head))
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> bool:
        return verify_chain(self._entries)


def verify_chain(entries: list[LedgerEntry] | tuple[LedgerEntry, ...]) -> bool:
    previous = GENESIS
    for index, entry in enumerate(entries):
        if entry.sequence != index or entry.previous_hash != previous:
            return False
        if entry.entry_hash != _entry_hash(entry.sequence, entry.record, entry.previous_hash):
            return False
        previous = entry.entry_hash
    return True
