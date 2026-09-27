"""Durable job queue for workflow steps, backed by Postgres."""

from greenloop_contracts import Dispatch


async def enqueue(item: Dispatch) -> None:
    raise NotImplementedError("TODO(phase-4): insert job row")


async def claim_next(worker_id: str) -> Dispatch | None:
    raise NotImplementedError("TODO(phase-4): SELECT ... FOR UPDATE SKIP LOCKED")
