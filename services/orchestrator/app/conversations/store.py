"""Owner-scoped conversations and their messages.

Every query filters by principal, and a conversation owned by someone else, or
deleted, looks exactly like a missing one. Deleting a conversation sets
deleted_at; messages are written once and never edited. The caller commits.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
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

    def history(self, conversation_id: str, limit: int) -> list[MessageRow]:
        """The newest `limit` complete messages, oldest first. Incomplete replies are skipped."""
        self.get(conversation_id)
        if limit == 0:
            return []
        rows = self._session.scalars(
            select(MessageRow)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.status == MessageStatus.COMPLETE.value,
            )
            .order_by(MessageRow.sequence.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))

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
