"""Chat engine: one user turn in, one streamed and stored assistant reply out.

prepare() validates, retrieves memory through the context builder, assembles the
request and stores the user message, all before any model call. run() streams the
reply through a StreamRedactor, so a secret split across chunks is still caught,
then stores it and audits the turn with provider, model, token usage and latency.

Streams are bounded by an idle timeout between provider events (text or Activity,
which providers emit while the model thinks), not a total deadline, so a long but
steady answer is never cut off while a stalled one is. If the client disconnects,
the provider fails mid-stream, or the reply hits the output-token limit
(AI_TRUNCATED), the text so far is kept as an incomplete message, which later
history leaves out. The engine never sees raw memory records, only the
MemoryContext.

prepare() takes the conversation's turn lease before anything else and _finish()
releases it with the reply, so turns can't interleave. The lease lasts the idle
timeout plus LEASE_MARGIN_SECONDS and is renewed at least every
RENEW_INTERVAL_SECONDS while events arrive, so it always outlives the idle timeout
of a live stream. A turn that never reaches _finish (process crash, a stream the
client dropped before it started) frees the conversation when the lease expires.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.ai.context import RequestLimits, build_turn_request
from app.ai.errors import AiError
from app.ai.providers.base import Done, GenerationRequest, Message, ModelProvider, TextDelta
from app.ai.providers.registry import ProviderRegistry
from app.audit import recorder
from app.conversations.store import ConversationNotFoundError, ConversationStore
from app.core.config import Settings
from app.core.redaction import Redactor
from app.db.models import MessageRole, MessageRow, MessageStatus
from app.memory import retrieval
from greenloop_contracts import AuditOutcome, AuditRecord

logger = structlog.get_logger(__name__)

LEASE_MARGIN_SECONDS = 30.0
RENEW_INTERVAL_SECONDS = 15.0


@dataclass(frozen=True)
class PreparedTurn:
    principal_id: str
    conversation_id: str
    correlation_id: str
    turn_id: str
    lease_started: float
    provider: ModelProvider
    request: GenerationRequest
    user_message: MessageRow
    memory_ids: tuple[str, ...]


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Finished:
    message: MessageRow


@dataclass(frozen=True)
class Failed:
    error: AiError
    partial_message: MessageRow | None


@dataclass(frozen=True)
class Abandoned:
    """The conversation was deleted mid-turn: the reply was discarded, the turn audited."""


EngineEvent = Delta | Finished | Failed | Abandoned


@dataclass(frozen=True)
class FinishResult:
    message: MessageRow | None
    abandoned: bool
    store_failed: bool


class ChatEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: ProviderRegistry,
        redactor: Redactor,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._redactor = redactor
        self._settings = settings
        self._started: set[str] = set()

    def prepare(
        self,
        principal_id: str,
        conversation_id: str,
        content: str,
        correlation_id: str,
        provider_name: str | None = None,
    ) -> PreparedTurn:
        """Take the turn lease, build the request and store the user message. Raises
        AiError, ConversationNotFoundError or ConversationBusyError; nothing is stored
        and no lease is kept when any of them is raised."""
        provider = self._registry.get(provider_name)
        settings = self._settings
        turn_id = f"turn-{uuid.uuid4().hex}"
        with self._session_factory() as session:
            store = ConversationStore(session, principal_id, correlation_id)
            store.claim_turn(conversation_id, turn_id, self._lease_seconds)
            lease_started = time.monotonic()
            history = [
                Message(role=row.role, content=row.content)
                for row in store.history(conversation_id, settings.ai_history_message_limit)
            ]
            records = retrieval.retrieve(
                session,
                principal_id,
                content,
                limit=settings.ai_memory_record_limit,
                correlation_id=correlation_id,
            )
            assembled = build_turn_request(
                records,
                history,
                content,
                principal_id=principal_id,
                redactor=self._redactor,
                limits=RequestLimits(
                    context_token_limit=settings.ai_context_token_limit,
                    max_output_tokens=settings.ai_max_output_tokens,
                ),
            )
            user_message = store.append(conversation_id, MessageRole.USER, content)
            session.commit()
        return PreparedTurn(
            principal_id=principal_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            turn_id=turn_id,
            lease_started=lease_started,
            provider=provider,
            request=assembled.request,
            user_message=user_message,
            memory_ids=assembled.memory_ids,
        )

    async def run(self, turn: PreparedTurn) -> AsyncIterator[EngineEvent]:
        self._started.add(turn.turn_id)
        started = time.perf_counter()
        redacting = self._redactor.stream()
        emitted: list[str] = []
        done = Done()
        events = turn.provider.stream(turn.request).__aiter__()
        failure: AiError | None = None
        last_renewal = turn.lease_started
        try:
            while True:
                event = await self._next(events)
                if event is None:
                    break
                if time.monotonic() - last_renewal >= RENEW_INTERVAL_SECONDS:
                    last_renewal = time.monotonic()
                    await asyncio.to_thread(self._renew, turn)
                if isinstance(event, Done):
                    done = event
                    break
                safe = redacting.feed(event.text) if isinstance(event, TextDelta) else ""
                if safe:
                    emitted.append(safe)
                    yield Delta(safe)
            tail = redacting.flush()
            if tail:
                emitted.append(tail)
                yield Delta(tail)
        except AiError as err:
            failure = err
        except (asyncio.CancelledError, GeneratorExit):
            # Synchronous on purpose: an await here could itself be cancelled.
            emitted.append(redacting.flush())
            self._finish(turn, "".join(emitted), done, started, AiError("client_disconnected"))
            raise
        except Exception:
            logger.error("chat_engine_unexpected_error", exc_info=True)
            failure = AiError("unavailable")
        finally:
            await _close(events)

        emitted.append(redacting.flush())
        text = "".join(emitted)
        if failure is None and done.truncated:
            failure = AiError("truncated")
        if failure is None and not text.strip():
            failure = AiError("invalid_response")
        result = await asyncio.to_thread(self._finish, turn, text, done, started, failure)
        if result.abandoned:
            yield Abandoned()
        elif result.store_failed:
            yield Failed(failure or AiError("unavailable"), None)
        elif failure is not None:
            yield Failed(failure, result.message)
        else:
            yield Finished(result.message)

    async def run_to_completion(self, turn: PreparedTurn) -> MessageRow:
        """The stored reply. Raises AiError, or ConversationNotFoundError if the
        conversation was deleted mid-turn."""
        async for event in self.run(turn):
            if isinstance(event, Finished):
                return event.message
            if isinstance(event, Failed):
                raise event.error
            if isinstance(event, Abandoned):
                raise ConversationNotFoundError(turn.conversation_id)
        raise AiError("invalid_response")

    async def _next(self, events: AsyncIterator) -> object | None:
        try:
            return await asyncio.wait_for(events.__anext__(), self._settings.ai_timeout_seconds)
        except StopAsyncIteration:
            return None
        except TimeoutError as err:
            raise AiError("timeout") from err

    @property
    def _lease_seconds(self) -> float:
        return self._settings.ai_timeout_seconds + LEASE_MARGIN_SECONDS

    def _renew(self, turn: PreparedTurn) -> None:
        """Extend the lease. A failure is logged, not raised: losing the lease risks an
        interleaved transcript, which is better than cutting off a live reply."""
        try:
            with self._session_factory() as session:
                store = ConversationStore(session, turn.principal_id, turn.correlation_id)
                renewed = store.renew_turn(turn.conversation_id, turn.turn_id, self._lease_seconds)
                session.commit()
        except Exception:
            logger.warning("chat_turn_lease_renew_failed", exc_info=True)
            return
        if not renewed:
            logger.warning("chat_turn_lease_lost", conversation_id=turn.conversation_id)

    def close_if_unstarted(self, turn: PreparedTurn) -> None:
        """Release the lease and audit a turn whose run() never began, for example an
        SSE client that disconnected before its body started streaming. No-op once
        run() has started: run() finishes its own turn."""
        if turn.turn_id in self._started:
            return
        self._started.add(turn.turn_id)
        self._finish(turn, "", Done(), time.perf_counter(), AiError("client_disconnected"))

    def _finish(
        self,
        turn: PreparedTurn,
        text: str,
        done: Done,
        started: float,
        failure: AiError | None,
    ) -> FinishResult:
        """Store the reply (partial text as incomplete), release the turn lease, audit
        the turn and log a trace, all in one transaction. Never raises.

        If the conversation was deleted mid-turn, the reply is discarded and the turn
        is audited as CONVERSATION_DELETED. If that transaction fails for any other
        reason, a second transaction still releases the lease and audits the turn as
        STORE_FAILED, so no turn goes unaudited while the database is reachable."""
        config = turn.provider.config
        details = {
            "provider": config.name,
            "model": config.model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "input_tokens": done.input_tokens,
            "output_tokens": done.output_tokens,
            "stop_reason": done.stop_reason,
            "memory_ids": list(turn.memory_ids),
            "user_message_id": turn.user_message.message_id,
            "assistant_message_id": None,
            "error": failure.api_code if failure else None,
        }
        try:
            result = self._store_turn(turn, text, done, failure, details)
        except Exception:
            logger.error("chat_turn_store_failed", exc_info=True)
            details["error"] = "STORE_FAILED"
            self._audit_after_store_failure(turn, details)
            result = FinishResult(message=None, abandoned=False, store_failed=True)
        if result.abandoned:
            event = "chat_turn_abandoned"
        elif details["error"]:
            event = "chat_turn_failed"
        else:
            event = "chat_turn_completed"
        logger.info(
            event,
            conversation_id=turn.conversation_id,
            provider_request_id=done.request_id,
            **{key: value for key, value in details.items() if key != "memory_ids"},
            memory_count=len(turn.memory_ids),
        )
        return result

    def _store_turn(
        self,
        turn: PreparedTurn,
        text: str,
        done: Done,
        failure: AiError | None,
        details: dict,
    ) -> FinishResult:
        config = turn.provider.config
        with self._session_factory() as session:
            store = ConversationStore(session, turn.principal_id, turn.correlation_id)
            store.release_turn(turn.conversation_id, turn.turn_id)
            message = None
            abandoned = False
            if text.strip():
                try:
                    message = store.append(
                        turn.conversation_id,
                        MessageRole.ASSISTANT,
                        text,
                        status=(
                            MessageStatus.COMPLETE if failure is None else MessageStatus.INCOMPLETE
                        ),
                        provider=config.name,
                        model=config.model,
                        input_tokens=done.input_tokens or None,
                        output_tokens=done.output_tokens or None,
                    )
                except ConversationNotFoundError:
                    abandoned = True
            if abandoned:
                details["error"] = "CONVERSATION_DELETED"
            details["assistant_message_id"] = message.message_id if message else None
            _record_turn_audit(session, turn, details)
            session.commit()
        return FinishResult(message=message, abandoned=abandoned, store_failed=False)

    def _audit_after_store_failure(self, turn: PreparedTurn, details: dict) -> None:
        try:
            with self._session_factory() as session:
                ConversationStore(session, turn.principal_id, turn.correlation_id).release_turn(
                    turn.conversation_id, turn.turn_id
                )
                _record_turn_audit(session, turn, details)
                session.commit()
        except Exception:
            # The database is unreachable: the lease expires on its own; the log is the trace.
            logger.error("chat_turn_audit_failed", exc_info=True)


def _record_turn_audit(session: Session, turn: PreparedTurn, details: dict) -> None:
    recorder.record(
        session,
        AuditRecord.model_validate(
            {
                "audit_id": f"aud-{turn.user_message.message_id.removeprefix('msg-')}",
                "principal_id": turn.principal_id,
                "actor": turn.principal_id,
                "action": "chat.turn",
                "resource_type": "conversation",
                "resource_id": turn.conversation_id,
                "outcome": AuditOutcome.FAILED if details["error"] else AuditOutcome.EXECUTED,
                "correlation_id": turn.correlation_id,
                "details": details,
            }
        ),
    )


async def _close(events: AsyncIterator) -> None:
    aclose = getattr(events, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        logger.warning("provider_stream_close_failed", exc_info=True)
