"""Owner-scoped conversations and their messages.

Every query filters by principal, and a conversation owned by someone else, or
deleted, looks exactly like a missing one. Deleting a conversation sets
deleted_at; messages are written once and never edited. The caller commits.

A chat turn holds a lease on its conversation from storing the user message to
storing the reply, so two turns can't interleave. The lease is taken with one
conditional UPDATE, which Postgres serializes on the row lock, and it expires so
a crashed turn frees the conversation on its own.
"""

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import recorder
from app.db.models import ConversationRow, MessageRole, MessageRow, MessageStatus
from greenloop_contracts import AuditOutcome, AuditRecord

MAX_SEQUENCE_ATTEMPTS = 5


class ConversationNotFoundError(LookupError):
    pass


class SequenceConflictError(Exception):
    pass


class ConversationBusyError(Exception):
    """Another turn holds this conversation's lease."""


class ConversationStore:
    def __init__(self, session: Session, principal_id: str, correlation_id: str) -> None:
        self._session = session
        self._principal_id = principal_id
        self._correlation_id = correlation_id

    def create(self, title: str) -> ConversationRow:
        now = datetime.now(UTC)
        row = ConversationRow(
            conversation_id=f"conv-{uuid.uuid4().hex}",
            principal_id=self._principal_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()
        self._audit("conversation.create", row.conversation_id)
        return row

    def list_active(self, *, limit: int, offset: int) -> tuple[list[ConversationRow], int]:
        conditions = (
            ConversationRow.principal_id == self._principal_id,
            ConversationRow.deleted_at.is_(None),
        )
        total = self._session.scalar(
            select(func.count()).select_from(ConversationRow).where(*conditions)
        )
        rows = self._session.scalars(
            select(ConversationRow)
            .where(*conditions)
            .order_by(ConversationRow.updated_at.desc(), ConversationRow.conversation_id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), total or 0

    def get(self, conversation_id: str) -> ConversationRow:
        row = self._owned(conversation_id)
        if row is None or row.deleted_at is not None:
            raise ConversationNotFoundError(conversation_id)
        return row

    def delete(self, conversation_id: str) -> None:
        """Soft delete. Repeating it on an already deleted conversation is a no-op."""
        row = self._owned(conversation_id)
        if row is None:
            raise ConversationNotFoundError(conversation_id)
        if row.deleted_at is None:
            row.deleted_at = datetime.now(UTC)
            self._audit("conversation.delete", conversation_id)

    def messages(
        self, conversation_id: str, *, limit: int, offset: int
    ) -> tuple[list[MessageRow], int]:
        self.get(conversation_id)
        condition = MessageRow.conversation_id == conversation_id
        total = self._session.scalar(select(func.count()).select_from(MessageRow).where(condition))
        rows = self._session.scalars(
            select(MessageRow)
            .where(condition)
            .order_by(MessageRow.sequence)
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), total or 0

    def message(self, conversation_id: str, message_id: str) -> MessageRow:
        """One message of an owned, live conversation; anything else is not found."""
        self.get(conversation_id)
        row = self._session.scalars(
            select(MessageRow).where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.message_id == message_id,
            )
        ).one_or_none()
        if row is None:
            raise ConversationNotFoundError(conversation_id)
        return row

    def is_answered(self, message: MessageRow) -> bool:
        """Whether a user message got a complete reply, the rule `history` uses to keep
        refused or failed turns out of later prompts."""
        reply = self._session.scalars(
            select(MessageRow).where(
                MessageRow.conversation_id == message.conversation_id,
                MessageRow.sequence == message.sequence + 1,
            )
        ).one_or_none()
        return (
            reply is not None
            and reply.role == MessageRole.ASSISTANT.value
            and reply.status == MessageStatus.COMPLETE.value
        )

    def history(self, conversation_id: str, limit: int) -> list[MessageRow]:
        """The newest `limit` messages from answered turns, oldest first.

        A user message is kept only together with the complete assistant reply right
        after it. A turn that was refused, rejected, failed, cut off or is still
        pending never reaches a later prompt, so one bad message can't break every
        turn after it, and history always alternates user/assistant. Turns don't
        interleave (the turn lease), so a reply always directly follows its message.
        """
        self.get(conversation_id)
        if limit == 0:
            return []
        window = self._session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.sequence.desc())
            .limit(limit * 2)
        ).all()
        window = list(reversed(window))
        answered: list[MessageRow] = []
        for message, reply in pairwise(window):
            if (
                message.role == MessageRole.USER.value
                and reply.role == MessageRole.ASSISTANT.value
                and reply.status == MessageStatus.COMPLETE.value
            ):
                answered += [message, reply]
        return answered[-limit:]

    def append(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        *,
        status: MessageStatus = MessageStatus.COMPLETE,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> MessageRow:
        """Add a message with the next sequence number.

        Two writers can pick the same number; the unique constraint rejects the loser,
        which retries with a fresh number inside a savepoint.
        """
        conversation = self.get(conversation_id)
        for _ in range(MAX_SEQUENCE_ATTEMPTS):
            now = datetime.now(UTC)
            row = MessageRow(
                message_id=f"msg-{uuid.uuid4().hex}",
                conversation_id=conversation_id,
                sequence=self._next_sequence(conversation_id),
                role=role.value,
                content=content,
                status=status.value,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                correlation_id=self._correlation_id,
                created_at=now,
                updated_at=now,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(row)
            except IntegrityError:
                continue
            conversation.updated_at = now
            return row
        raise SequenceConflictError(conversation_id)

    def claim_turn(self, conversation_id: str, turn_id: str, lease_seconds: float) -> None:
        """Take the turn lease if it is free or expired. Raises ConversationBusyError,
        or ConversationNotFoundError for a missing, deleted or foreign conversation."""
        now = datetime.now(UTC)
        claimed = self._session.execute(
            update(ConversationRow)
            .where(
                ConversationRow.conversation_id == conversation_id,
                ConversationRow.principal_id == self._principal_id,
                ConversationRow.deleted_at.is_(None),
                or_(
                    ConversationRow.active_turn_id.is_(None),
                    ConversationRow.turn_lease_expires_at < now,
                ),
            )
            .values(
                active_turn_id=turn_id,
                turn_lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed == 0:
            self.get(conversation_id)
            raise ConversationBusyError(conversation_id)

    def renew_turn(self, conversation_id: str, turn_id: str, lease_seconds: float) -> bool:
        """Extend the lease if `turn_id` still holds it; False means it was lost."""
        return self._update_lease(
            conversation_id,
            turn_id,
            turn_lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )

    def release_turn(self, conversation_id: str, turn_id: str) -> None:
        """Free the lease if `turn_id` still holds it. Works on a deleted conversation."""
        self._update_lease(
            conversation_id, turn_id, active_turn_id=None, turn_lease_expires_at=None
        )

    def _update_lease(self, conversation_id: str, turn_id: str, **values: object) -> bool:
        return (
            self._session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.conversation_id == conversation_id,
                    ConversationRow.principal_id == self._principal_id,
                    ConversationRow.active_turn_id == turn_id,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ).rowcount
            > 0
        )

    def _owned(self, conversation_id: str) -> ConversationRow | None:
        return self._session.scalars(
            select(ConversationRow).where(
                ConversationRow.conversation_id == conversation_id,
                ConversationRow.principal_id == self._principal_id,
            )
        ).one_or_none()

    def _next_sequence(self, conversation_id: str) -> int:
        current = self._session.scalar(
            select(func.max(MessageRow.sequence)).where(
                MessageRow.conversation_id == conversation_id
            )
        )
        return (current or 0) + 1

    def _audit(self, action: str, conversation_id: str) -> None:
        recorder.record(
            self._session,
            AuditRecord(
                audit_id=f"aud-{uuid.uuid4().hex}",
                principal_id=self._principal_id,
                actor=self._principal_id,
                action=action,
                resource_type="conversation",
                resource_id=conversation_id,
                outcome=AuditOutcome.EXECUTED,
                correlation_id=self._correlation_id,
            ),
        )
