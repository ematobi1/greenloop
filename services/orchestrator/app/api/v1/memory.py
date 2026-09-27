"""Memory records: list, create, read, and delete (a tombstone, never a hard delete).

TODO(phase-2): scope every query to the authenticated principal and record provenance.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/memory-records", tags=["memory"])


@router.get("")
async def list_memory_records() -> None:
    raise not_implemented("Memory listing", phase=2)


@router.post("", status_code=201)
async def create_memory_record() -> None:
    raise not_implemented("Memory creation", phase=2)


@router.get("/{record_id}")
async def get_memory_record(record_id: str) -> None:
    raise not_implemented("Memory lookup", phase=2)


@router.get("/{record_id}/history")
async def get_memory_history(record_id: str) -> None:
    raise not_implemented("Memory history", phase=2)


@router.delete("/{record_id}", status_code=204)
async def delete_memory_record(record_id: str) -> None:
    raise not_implemented("Memory deletion", phase=2)
