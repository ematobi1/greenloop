"""Conversations and messages: the chat entry point.

POST /{id}/messages stores the user message, then answers either as JSON (the
whole reply) or, when the client sends `Accept: text/event-stream`, as SSE:
`message` (the stored user message), `delta` events, then `done` (the stored reply)
or `error` (`{"error": ErrorDetail}`, the same shape as every JSON error, plus
`partial_message`: any partial reply that was kept). While a
turn is in flight, another message to the same conversation gets 409
CONVERSATION_BUSY and is not stored. If the conversation is deleted mid-turn, the
reply is discarded and the client gets CONVERSATION_NOT_FOUND (404, or an SSE
`error` event).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.ai.engine import Abandoned, ChatEngine, Delta, Failed, Finished, PreparedTurn
from app.ai.errors import AiError
from app.api.v1.pagination import Limit, Offset, PageMeta
from app.conversations.store import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationStore,
    SequenceConflictError,
)
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError, error_body
from app.db.models import MessageRow, MessageStatus
from app.db.session import get_session
from app.memory import provenance
from app.memory.indexing import index_record
from app.memory.store import MemoryStore
from greenloop_contracts import (
    MemoryCategory,
    MemoryOperation,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    Provenance,
)

router = APIRouter(prefix="/conversations", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
ConversationId = Annotated[str, Path(max_length=128)]
MessageId = Annotated[str, Path(max_length=128)]
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

    @field_validator("content")
    @classmethod
    def _not_blank(cls, content: str) -> str:
        if not content.strip():
            raise ValueError("Must contain non-whitespace text.")
        return content


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


class RememberCreate(BaseModel):
    """Save a chat message as memory. `content` lets the user keep only part of it."""

    model_config = ConfigDict(extra="forbid")

    content: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
        | None
    ) = None
    category: MemoryCategory = MemoryCategory.USER_CONTEXT


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
        state.session_factory,
        state.provider_registry,
        state.redactor,
        state.settings,
        embedder=state.embedder,
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
    query_vector = await engine.embed_query(body.content)
    try:
        turn = await asyncio.to_thread(
            engine.prepare,
            principal.principal_id,
            conversation_id,
            body.content,
            request.state.correlation_id,
            body.provider,
            query_vector,
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
        return TurnStreamingResponse(
            _event_stream(engine, turn),
            on_close=partial(engine.close_if_unstarted, turn),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    try:
        reply = await engine.run_to_completion(turn)
    except ConversationNotFoundError:
        raise _not_found() from None
    except AiError as err:
        raise err.to_api_error() from None
    return TurnResult(
        user_message=MessageOut.model_validate(turn.user_message),
        assistant_message=MessageOut.model_validate(reply),
    )


class TurnStreamingResponse(StreamingResponse):
    """Runs `on_close` after the response ends however it ends, shielded from
    cancellation. Starlette may never start the body generator if the client
    disconnects while headers are sent, and an unstarted generator runs no
    `finally`, so turn cleanup can't live inside the generator alone."""

    def __init__(self, content: AsyncIterator[str], *, on_close: Callable[[], None], **kwargs):
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._on_close)


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
                    error_body(event.error.api_code, event.error.public_message)
                    | {"partial_message": _message_json(event.partial_message)},
                )
            elif isinstance(event, Abandoned):
                error = _not_found()
                yield _sse(
                    "error", error_body(error.code, error.message) | {"partial_message": None}
                )
    finally:
        await events.aclose()


@router.post("/{conversation_id}/messages/{message_id}/remember", status_code=201)
def remember_message(
    conversation_id: ConversationId,
    message_id: MessageId,
    body: RememberCreate,
    request: Request,
    principal: CurrentPrincipal,
    store: Store,
    session: DbSession,
) -> MemoryRecord:
    """Explicit "remember this": the user, not the model, decides what becomes memory.

    The record is the principal's own, private, unverified, with provenance source=user
    and source_ref pointing at the conversation and message it came from.
    """
    try:
        message = store.message(conversation_id, message_id)
    except ConversationNotFoundError:
        raise ApiError(404, "MESSAGE_NOT_FOUND", "Message not found.") from None
    if message.status != MessageStatus.COMPLETE.value:
        raise ApiError(422, "MESSAGE_INCOMPLETE", "Only a complete message can be saved as memory.")
    content = body.content or message.content.strip()
    if not content or len(content) > 20000:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "Request validation failed.",
            fields={"content": "Choose 1 to 20000 characters to remember."},
        )
    source_ref = f"conversation:{conversation_id}/message:{message_id}"
    memory = MemoryStore(session, request.state.correlation_id)
    if memory.live_by_source_ref(principal.principal_id, source_ref) is not None:
        raise ApiError(409, "ALREADY_REMEMBERED", "This message is already saved as memory.")
    record = MemoryRecord(
        record_id=provenance.new_record_id(),
        principal_id=principal.principal_id,
        scope=MemoryScope.PRIVATE,
        category=body.category,
        content=content,
        provenance=Provenance(
            source=MemorySource.USER,
            source_ref=source_ref,
            created_by=principal.principal_id,
            operation=MemoryOperation.CREATE,
        ),
        created_at=datetime.now(UTC),
    )
    memory.create(record)
    index_record(session, request.app.state.embedder, record)
    session.commit()
    return record
