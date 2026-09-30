"""Conversations and messages: the chat entry point.

POST /{id}/messages stores the user message, then answers either as JSON (the
whole reply) or, when the client sends `Accept: text/event-stream`, as SSE:
`message` (the stored user message), `delta` events, then `done` (the stored reply)
or `error` (a safe code and message, plus any partial reply that was kept). While a
turn is in flight, another message to the same conversation gets 409
CONVERSATION_BUSY and is not stored.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.ai.engine import ChatEngine, Delta, Failed, Finished, PreparedTurn
from app.ai.errors import AiError
from app.api.v1.pagination import Limit, Offset, PageMeta
from app.conversations.store import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationStore,
    SequenceConflictError,
)
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.db.models import MessageRow
from app.db.session import get_session

router = APIRouter(prefix="/conversations", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
ConversationId = Annotated[str, Path(max_length=128)]
DbSession = Annotated[Session, Depends(get_session)]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = "New conversation"


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, StringConstraints(min_length=1, max_length=200000)]
    provider: Annotated[str, StringConstraints(max_length=32)] | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    conversation_id: str
    sequence: int
    role: str
    content: str
    status: str
    provider: str | None
    model: str | None
    created_at: datetime


class ConversationPage(BaseModel):
    data: list[ConversationOut]
    meta: PageMeta


class MessagePage(BaseModel):
    data: list[MessageOut]
    meta: PageMeta


class TurnResult(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


def _store(request: Request, session: DbSession, principal: CurrentPrincipal) -> ConversationStore:
    return ConversationStore(session, principal.principal_id, request.state.correlation_id)


def _engine(request: Request) -> ChatEngine:
    state = request.app.state
    if state.session_factory is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not configured.")
    return ChatEngine(
        state.session_factory, state.provider_registry, state.redactor, state.settings
    )


Store = Annotated[ConversationStore, Depends(_store)]
Engine = Annotated[ChatEngine, Depends(_engine)]


def _not_found() -> ApiError:
    return ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found.")


@router.post("", status_code=201)
def create_conversation(
    body: ConversationCreate, store: Store, session: DbSession
) -> ConversationOut:
    row = store.create(body.title)
    session.commit()
    return ConversationOut.model_validate(row)


@router.get("")
def list_conversations(store: Store, limit: Limit = 50, offset: Offset = 0) -> ConversationPage:
    rows, total = store.list_active(limit=limit, offset=offset)
    return ConversationPage(
        data=[ConversationOut.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/{conversation_id}")
def get_conversation(conversation_id: ConversationId, store: Store) -> ConversationOut:
    try:
        return ConversationOut.model_validate(store.get(conversation_id))
    except ConversationNotFoundError:
        raise _not_found() from None


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: ConversationId, store: Store, session: DbSession
) -> Response:
    try:
        store.delete(conversation_id)
    except ConversationNotFoundError:
        raise _not_found() from None
    session.commit()
    return Response(status_code=204)


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: ConversationId, store: Store, limit: Limit = 100, offset: Offset = 0
) -> MessagePage:
    try:
        rows, total = store.messages(conversation_id, limit=limit, offset=offset)
    except ConversationNotFoundError:
        raise _not_found() from None
    return MessagePage(
        data=[MessageOut.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.post(
    "/{conversation_id}/messages",
    status_code=201,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream"}},
)
async def send_message(
    conversation_id: ConversationId,
    body: MessageCreate,
    request: Request,
    principal: CurrentPrincipal,
    engine: Engine,
) -> TurnResult:
    settings = request.app.state.settings
    if len(body.content) > settings.ai_max_message_chars:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "Request validation failed.",
            fields={"content": f"At most {settings.ai_max_message_chars} characters."},
        )
    try:
        turn = await asyncio.to_thread(
            engine.prepare,
            principal.principal_id,
            conversation_id,
            body.content,
            request.state.correlation_id,
            body.provider,
        )
    except ConversationNotFoundError:
        raise _not_found() from None
    except ConversationBusyError:
        raise ApiError(
            409,
            "CONVERSATION_BUSY",
            "A reply is still being written in this conversation. Send again when it finishes.",
        ) from None
    except AiError as err:
        raise err.to_api_error() from None
    except SequenceConflictError:
        raise ApiError(
            409, "MESSAGE_SEQUENCE_CONFLICT", "Could not order the message. Retry."
        ) from None

    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            _event_stream(engine, turn), media_type="text/event-stream", headers=SSE_HEADERS
        )
    try:
        reply = await engine.run_to_completion(turn)
    except AiError as err:
        raise err.to_api_error() from None
    return TurnResult(
        user_message=MessageOut.model_validate(turn.user_message),
        assistant_message=MessageOut.model_validate(reply),
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _message_json(message: MessageRow | None) -> dict | None:
    return MessageOut.model_validate(message).model_dump(mode="json") if message else None


async def _event_stream(engine: ChatEngine, turn: PreparedTurn) -> AsyncIterator[str]:
    yield _sse("message", {"user_message": _message_json(turn.user_message)})
    events = engine.run(turn)
    try:
        async for event in events:
            if isinstance(event, Delta):
                yield _sse("delta", {"text": event.text})
            elif isinstance(event, Finished):
                yield _sse("done", {"assistant_message": _message_json(event.message)})
            elif isinstance(event, Failed):
                yield _sse(
                    "error",
                    {
                        "code": event.error.api_code,
                        "message": event.error.public_message,
                        "partial_message": _message_json(event.partial_message),
                    },
                )
    finally:
        await events.aclose()
