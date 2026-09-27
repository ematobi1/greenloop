"""Liveness endpoint. Unversioned and unauthenticated so load balancers can probe it."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
