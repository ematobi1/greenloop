"""Aggregates the versioned v1 routers under /v1."""

from fastapi import APIRouter

from app.api.v1 import agents, approvals, audit, chat, memory, plans

router = APIRouter(prefix="/v1")
for module in (chat, memory, plans, agents, approvals, audit):
    router.include_router(module.router)
