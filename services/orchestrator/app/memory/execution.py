"""Execution memory: one task_execution_history record per dispatch.

The content is only what the dispatcher observed (ids, status, times, error code),
never the dispatch inputs or agent output, which can hold user data or injected text.
That is why confidence is verified. Scope is private to the dispatching principal.

The record id is derived from the dispatch id, so recording the same dispatch twice
is reported as already recorded rather than creating a second record.
"""

import json
from enum import StrEnum

from sqlalchemy.exc import IntegrityError

from app.memory.store import MemoryNotFoundError, MemoryStore
from greenloop_contracts import (
    Dispatch,
    ExecutionResult,
    MemoryCategory,
    MemoryConfidence,
    MemoryOperation,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    Provenance,
)


class ExecutionMemoryStatus(StrEnum):
    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    FAILED = "failed"


def execution_record_id(dispatch_id: str) -> str:
    return f"mem-exec-{dispatch_id.removeprefix('dsp-')}"


def execution_record(item: Dispatch, result: ExecutionResult) -> MemoryRecord:
    content = json.dumps(
        {
            "dispatch_id": item.dispatch_id,
            "task_id": item.task_id,
            "agent_id": item.agent_id,
            "status": result.status.value,
            "error_code": result.error.code if result.error else None,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
        },
        sort_keys=True,
    )
    return MemoryRecord(
        record_id=execution_record_id(item.dispatch_id),
        principal_id=item.principal_id,
        scope=MemoryScope.PRIVATE,
        category=MemoryCategory.TASK_EXECUTION_HISTORY,
        confidence=MemoryConfidence.VERIFIED,
        content=content,
        related_task_id=item.task_id,
        provenance=Provenance(
            source=MemorySource.AGENT,
            source_ref=f"dispatch:{item.dispatch_id}",
            created_by=item.agent_id,
            operation=MemoryOperation.CREATE,
        ),
        created_at=result.finished_at,
    )


def record_execution(
    store: MemoryStore, item: Dispatch, result: ExecutionResult
) -> ExecutionMemoryStatus:
    """Adds the record to the store's session. Raises on database errors other than
    the record already existing; the caller decides what a failure means."""
    record = execution_record(item, result)
    try:
        store.create(record)
    except IntegrityError as err:
        try:
            store.get(item.principal_id, record.record_id)
        except MemoryNotFoundError:
            raise err from None
        return ExecutionMemoryStatus.ALREADY_RECORDED
    return ExecutionMemoryStatus.RECORDED
