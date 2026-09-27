"""Provenance operations: build the new record for supersede, correct and delete.

Each returns a new MemoryRecord linked to the original; nothing is edited in place.
"""

from greenloop_contracts import MemoryRecord


def supersede(original: MemoryRecord, new_content: str, actor_id: str) -> MemoryRecord:
    raise NotImplementedError("TODO(phase-2): new record with operation=supersede")


def correct(original: MemoryRecord, corrected_content: str, actor_id: str) -> MemoryRecord:
    raise NotImplementedError("TODO(phase-2): new record with operation=correct")


def tombstone(original: MemoryRecord, actor_id: str) -> MemoryRecord:
    raise NotImplementedError("TODO(phase-2): empty-content record with operation=delete")
