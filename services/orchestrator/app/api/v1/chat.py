"""Conversations and messages: the main chat entry point.

TODO(phase-2): authenticate, retrieve memory through the context builder, reason,
draft a plan when needed, store new memory, and return the reply.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/conversations", tags=["chat"])


@router.post("", status_code=201)
async def create_conversation() -> None:
    raise not_implemented("Conversations", phase=2)


@router.post("/{conversation_id}/messages", status_code=201)
async def send_message(conversation_id: str) -> None:
    raise not_implemented("Chat messages", phase=2)
