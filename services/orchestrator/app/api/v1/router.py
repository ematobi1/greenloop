"""Aggregates the versioned v1 routers under /v1."""

from fastapi import APIRouter

from app.api.v1 import agents, approvals, audit, chat, dispatches, memory, plans, sessions

router = APIRouter(prefix="/v1")
for module in (sessions, chat, memory, plans, agents, dispatches, approvals, audit):
    router.include_router(module.router)
