"""ApprovalStore on Postgres: binding, expiry by the database clock, single use,
idempotency, owner scoping and audit of every outcome (ADR 0009 rules 3-9)."""

import threading
import uuid

import pytest
from sqlalchemy import select, text
from tests.integration.pg import TEST_DATABASE_URL

from app.approval_store import ApprovalRefusal, ApprovalRefusedError, summarize
from app.db.tables import approvals, audit_events
from greenloop_contracts import ApprovalStatus, operation_hash

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

ACTOR = "orchestrator"


def key() -> str:
    return f"idem-{uuid.uuid4().hex}"


@pytest.fixture
def owner() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def operation(permission, owner):
    return permission(principal_id=owner, repo="greenloop", title=f"Bug {uuid.uuid4().hex[:6]}")


def create(store, operation, idempotency_key=None):
    return store.create(
        operation, idempotency_key=idempotency_key or key(), actor=ACTOR, correlation_id="corr-1"
    )


def decide(store, approval, approved=True, idempotency_key=None, decided_by=None):
    return store.decide(
        approval.approval_id,
        decided_by=decided_by or approval.principal_id,
        approved=approved,
        idempotency_key=idempotency_key or key(),
        actor=ACTOR,
        correlation_id="corr-2",
    )


def consume(store, approval_id, operation):
    return store.consume(approval_id, operation, actor=ACTOR, correlation_id="corr-3")


def events(engine, **where):
    with engine.connect() as connection:
        statement = select(audit_events).order_by(audit_events.c.created_at)
        for column, value in where.items():
            statement = statement.where(audit_events.c[column] == value)
        return list(connection.execute(statement).mappings())


def row(engine, approval_id):
    with engine.connect() as connection:
        return (
            connection.execute(select(approvals).where(approvals.c.approval_id == approval_id))
            .mappings()
            .one()
        )


AGE_PENDING = text(
    "UPDATE broker.approvals SET created_at = now() - interval '20 minutes',"
    " expires_at = now() - interval '5 minutes' WHERE approval_id = :id"
)
AGE_DECIDED = text(
    "UPDATE broker.approvals SET created_at = now() - interval '20 minutes',"
    " decided_at = now() - interval '19 minutes', expires_at = now() - interval '5 minutes'"
    " WHERE approval_id = :id"
)


def age(db_roles, approval_id, *, decided: bool = False):
    """Moves an approval into the past by the database clock, so it has expired."""
    with db_roles.admin_engine.begin() as connection:
        connection.execute(AGE_DECIDED if decided else AGE_PENDING, {"id": approval_id})


def refused(reason):
    return pytest.raises(ApprovalRefusedError, match=f"^{reason.value}$")


# create


def test_create_binds_the_exact_operation_and_expires_by_the_ttl(store, engine, operation):
    approval = create(store, operation)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.operation == operation
    assert approval.operation_hash == operation_hash(operation)
    assert approval.summary == summarize(operation)
    assert approval.expires_at - approval.created_at == store._ttl
    [event] = events(engine, approval_id=approval.approval_id)
    assert (event["action"], event["outcome"]) == ("approval.create", "approval_required")
    assert event["operation_hash"] == approval.operation_hash


def test_a_repeated_create_returns_the_same_approval_once(store, engine, operation):
    idempotency_key = key()
    first = create(store, operation, idempotency_key)
    second = create(store, operation, idempotency_key)
    assert second == first
    assert len(events(engine, approval_id=first.approval_id)) == 1


def test_the_same_key_for_a_different_operation_is_refused_and_audited(
    store, engine, permission, operation, owner
):
    idempotency_key = key()
    first = create(store, operation, idempotency_key)
    other = permission(principal_id=owner, repo="greenloop", title="Something else")
    with refused(ApprovalRefusal.IDEMPOTENCY_CONFLICT):
        create(store, other, idempotency_key)
    [denied] = events(engine, operation_hash=operation_hash(other))
    assert (denied["outcome"], denied["details"]) == ("denied", {"reason": "idempotency_conflict"})
    assert store.list_for(owner) == ([first], 1)


def test_idempotency_keys_are_per_principal(store, permission):
    idempotency_key = key()
    first = create(store, permission(principal_id="user-a", n=1), idempotency_key)
    second = create(store, permission(principal_id="user-b", n=1), idempotency_key)
    assert first.approval_id != second.approval_id


def test_the_summary_escapes_lookalike_characters(store, permission, owner):
    approval = create(store, permission(principal_id=owner, payee="p" + chr(0x430) + "ypal"))
    assert "p\\u0430ypal" in approval.summary
    assert approval.summary.isascii()


def test_the_summary_is_capped(store, permission, owner):
    approval = create(store, permission(principal_id=owner, body="x" * 2000))
    assert len(approval.summary) == 500
    assert approval.summary.endswith("...")


@pytest.mark.parametrize("value", [1e16, 1.0, 1, 0.1, -0.0, 12345678901234567890, "é"])
def test_stored_operations_keep_their_exact_values_and_hash(store, permission, owner, value):
    operation = permission(principal_id=owner, amount=value)
    approval = create(store, operation)
    stored = store.get(approval.approval_id, principal_id=owner)
    assert stored.operation_hash == operation_hash(stored.operation) == operation_hash(operation)


# get and list


def test_get_and_list_are_scoped_to_the_owner(store, operation, owner):
    approval = create(store, operation)
    assert store.get(approval.approval_id, principal_id=owner) == approval
    assert store.get(approval.approval_id, principal_id="someone-else") is None
    assert store.list_for("someone-else") == ([], 0)


def test_list_filters_by_status_newest_first(store, permission, owner):
    first = create(store, permission(principal_id=owner, n=1))
    second = create(store, permission(principal_id=owner, n=2))
    decided = decide(store, first)
    assert [a.approval_id for a in store.list_for(owner)[0]] == [
        second.approval_id,
        first.approval_id,
    ]
    assert store.list_for(owner, status=ApprovalStatus.APPROVED) == ([decided], 1)
    assert store.list_for(owner, status=ApprovalStatus.PENDING) == ([second], 1)
    page, total = store.list_for(owner, limit=1)
    assert (len(page), total) == (1, 2)


def test_an_expired_pending_approval_is_not_listed_as_pending(store, db_roles, permission, owner):
    live = create(store, permission(principal_id=owner, n=1))
    stale = create(store, permission(principal_id=owner, n=2))
    age(db_roles, stale.approval_id)
    pending, total = store.list_for(owner, status=ApprovalStatus.PENDING)
    assert ([a.approval_id for a in pending], total) == ([live.approval_id], 1)
    assert store.list_for(owner)[1] == 2


# decide


@pytest.mark.parametrize(("approved", "status"), [(True, "approved"), (False, "rejected")])
def test_the_owner_decides_once_and_it_is_audited(store, engine, operation, approved, status):
    approval = create(store, operation)
    decided = decide(store, approval, approved=approved)
    assert decided.status == status
    assert decided.decided_by == approval.principal_id
    assert approval.created_at <= decided.decided_at < decided.expires_at
    assert [e["outcome"] for e in events(engine, approval_id=approval.approval_id)] == [
        "approval_required",
        status,
    ]


def test_someone_else_cannot_decide_and_learns_nothing(store, engine, operation):
    approval = create(store, operation)
    with refused(ApprovalRefusal.NOT_FOUND):
        decide(store, approval, decided_by="intruder")
    assert row(engine, approval.approval_id)["status"] == "pending"
    [denied] = events(engine, principal_id="intruder")
    assert (denied["action"], denied["outcome"]) == ("approval.decide", "denied")
    assert denied["approval_id"] is None
    assert denied["resource_id"] == approval.approval_id


def test_an_unknown_approval_cannot_be_decided(store, owner):
    with refused(ApprovalRefusal.NOT_FOUND):
        store.decide(
            "apr-missing",
            decided_by=owner,
            approved=True,
            idempotency_key=key(),
            actor=ACTOR,
            correlation_id="c",
        )


def test_a_decided_approval_cannot_be_decided_again(store, engine, operation):
    approval = create(store, operation)
    decide(store, approval, approved=True)
    with refused(ApprovalRefusal.NOT_PENDING):
        decide(store, approval, approved=False)
    assert row(engine, approval.approval_id)["status"] == "approved"


def test_a_repeated_decision_returns_the_stored_result(store, engine, operation):
    approval = create(store, operation)
    idempotency_key = key()
    first = decide(store, approval, idempotency_key=idempotency_key)
    assert decide(store, approval, idempotency_key=idempotency_key) == first
    assert len(events(engine, approval_id=approval.approval_id)) == 2


def test_a_repeated_approval_after_consume_returns_the_consumed_approval(store, operation):
    approval = create(store, operation)
    idempotency_key = key()
    decide(store, approval, idempotency_key=idempotency_key)
    consumed = consume(store, approval.approval_id, operation)
    assert decide(store, approval, idempotency_key=idempotency_key) == consumed


def test_the_same_decision_key_with_the_opposite_answer_is_refused(store, engine, operation):
    approval = create(store, operation)
    idempotency_key = key()
    decide(store, approval, approved=True, idempotency_key=idempotency_key)
    with refused(ApprovalRefusal.IDEMPOTENCY_CONFLICT):
        decide(store, approval, approved=False, idempotency_key=idempotency_key)
    assert row(engine, approval.approval_id)["status"] == "approved"


def test_an_expired_approval_cannot_be_decided(store, engine, db_roles, operation):
    approval = create(store, operation)
    age(db_roles, approval.approval_id)
    with refused(ApprovalRefusal.EXPIRED):
        decide(store, approval)
    assert row(engine, approval.approval_id)["status"] == "pending"


# consume


@pytest.fixture
def approved(store, operation):
    return decide(store, create(store, operation))


def test_an_approved_operation_is_consumed_once(store, engine, approved, operation):
    consumed = consume(store, approved.approval_id, operation)
    assert consumed.status is ApprovalStatus.CONSUMED
    assert consumed.decided_at <= consumed.consumed_at < consumed.expires_at
    with refused(ApprovalRefusal.ALREADY_CONSUMED):
        consume(store, approved.approval_id, operation)
    outcomes = [
        e["outcome"]
        for e in events(engine, action="approval.consume", approval_id=approved.approval_id)
    ]
    assert outcomes == ["allowed", "denied"]


def test_a_different_operation_is_refused_without_using_up_the_approval(
    store, engine, approved, permission, owner, operation
):
    changed = permission(principal_id=owner, repo="greenloop", title="Different title")
    with refused(ApprovalRefusal.OPERATION_MISMATCH):
        consume(store, approved.approval_id, changed)
    [denied] = events(engine, action="approval.consume", approval_id=approved.approval_id)
    assert denied["details"] == {
        "reason": "operation_mismatch",
        "attempted_operation_hash": operation_hash(changed),
    }
    assert consume(store, approved.approval_id, operation).status is ApprovalStatus.CONSUMED


def test_another_principal_cannot_consume_it(store, approved, permission, operation):
    theirs = permission(principal_id="intruder", **operation.arguments)
    with refused(ApprovalRefusal.NOT_FOUND):
        consume(store, approved.approval_id, theirs)
    assert consume(store, approved.approval_id, operation).status is ApprovalStatus.CONSUMED


def test_a_pending_or_rejected_approval_cannot_be_consumed(store, permission, owner):
    pending_operation = permission(principal_id=owner, n=1)
    pending = create(store, pending_operation)
    with refused(ApprovalRefusal.NOT_APPROVED):
        consume(store, pending.approval_id, pending_operation)
    rejected_operation = permission(principal_id=owner, n=2)
    rejected = decide(store, create(store, rejected_operation), approved=False)
    with refused(ApprovalRefusal.NOT_APPROVED):
        consume(store, rejected.approval_id, rejected_operation)


def test_an_expired_approval_cannot_be_consumed(store, engine, db_roles, approved, operation):
    age(db_roles, approved.approval_id, decided=True)
    with refused(ApprovalRefusal.EXPIRED):
        consume(store, approved.approval_id, operation)
    assert row(engine, approved.approval_id)["status"] == "approved"


def test_an_unknown_approval_cannot_be_consumed(store, engine, operation):
    with refused(ApprovalRefusal.NOT_FOUND):
        consume(store, "apr-missing", operation)
    [denied] = events(engine, resource_id="apr-missing", action="approval.consume")
    assert denied["approval_id"] is None


def test_concurrent_consumes_succeed_exactly_once(store, engine, approved, operation):
    attempts = 8
    barrier = threading.Barrier(attempts)
    results: list[str] = []
    lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            consume(store, approved.approval_id, operation)
            outcome = "consumed"
        except ApprovalRefusedError as error:
            outcome = error.reason.value
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["already_consumed"] * (attempts - 1) + ["consumed"]
    allowed = events(engine, approval_id=approved.approval_id, outcome="allowed")
    assert len(allowed) == 1
