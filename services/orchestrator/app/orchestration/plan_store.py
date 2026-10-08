"""Drafted plans, scoped to their principal. A plan someone else owns looks missing.

Discarding is a soft status change; a discarded plan stays readable. Every write is
audited in the same transaction. The caller commits.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import recorder
from app.db.models import PlanRow
from greenloop_contracts import AuditOutcome, AuditRecord, Plan, PlanStatus, PlanStep


class PlanNotFoundError(LookupError):
    pass


class PlanStore:
    def __init__(self, session: Session, principal_id: str, correlation_id: str) -> None:
        self._session = session
        self._principal_id = principal_id
        self._correlation_id = correlation_id

    def create(
        self,
        goal: str,
        steps: tuple[PlanStep, ...],
        conversation_id: str | None,
        usage: dict[str, str | int] | None = None,
    ) -> Plan:
        """Store a draft. `usage` (provider, model, tokens) goes into the audit record."""
        now = datetime.now(UTC)
        plan = Plan(
            plan_id=f"plan-{uuid.uuid4().hex}",
            principal_id=self._principal_id,
            goal=goal,
            steps=steps,
            conversation_id=conversation_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(
            PlanRow(
                plan_id=plan.plan_id,
                principal_id=plan.principal_id,
                conversation_id=plan.conversation_id,
                goal=plan.goal,
                status=plan.status.value,
                steps=[step.model_dump(mode="json") for step in plan.steps],
                created_at=now,
                updated_at=now,
            )
        )
        self._audit("plan.draft", plan.plan_id, {"steps": len(plan.steps), **(usage or {})})
        return plan

    def list(
        self, *, limit: int, offset: int, status: PlanStatus | None = None
    ) -> tuple[list[Plan], int]:
        condition = PlanRow.principal_id == self._principal_id
        if status is not None:
            condition = condition & (PlanRow.status == status.value)
        total = self._session.scalar(select(func.count()).select_from(PlanRow).where(condition))
        rows = self._session.scalars(
            select(PlanRow)
            .where(condition)
            .order_by(PlanRow.created_at.desc(), PlanRow.plan_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [row.to_contract() for row in rows], total or 0

    def get(self, plan_id: str) -> Plan:
        return self._row(plan_id).to_contract()

    def discard(self, plan_id: str) -> None:
        row = self._row(plan_id)
        if row.status != PlanStatus.DISCARDED.value:
            row.status = PlanStatus.DISCARDED.value
            row.updated_at = datetime.now(UTC)
            self._audit("plan.discard", plan_id, {})

    def _row(self, plan_id: str) -> PlanRow:
        row = self._session.scalars(
            select(PlanRow).where(
                PlanRow.plan_id == plan_id, PlanRow.principal_id == self._principal_id
            )
        ).one_or_none()
        if row is None:
            raise PlanNotFoundError(plan_id)
        return row

    def _audit(self, action: str, plan_id: str, details: dict[str, str | int]) -> None:
        recorder.record(
            self._session,
            AuditRecord(
                audit_id=f"aud-{uuid.uuid4().hex}",
                principal_id=self._principal_id,
                actor="orchestrator",
                action=action,
                resource_type="plan",
                resource_id=plan_id,
                outcome=AuditOutcome.EXECUTED,
                correlation_id=self._correlation_id,
                details=details,
            ),
        )
