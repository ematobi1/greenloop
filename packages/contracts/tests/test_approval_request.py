import pytest
from pydantic import ValidationError

from greenloop_contracts import (
    ActorKind,
    ApprovalActor,
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ToolPermission,
)

OPERATION = ToolPermission(
    principal_id="user-1",
    tool="github",
    operation="create_issue",
    consequence="write",
    arguments={"repo": "greenloop"},
)


def actor(**overrides) -> dict:
    return {"principal_id": "user-1", "kind": "user", "in_dispatch": False} | overrides


@pytest.mark.parametrize(
    ("kind", "in_dispatch", "may_decide"),
    [
        ("user", False, True),
        ("user", True, False),
        ("system", False, False),
        ("system", True, False),
    ],
)
def test_only_a_user_outside_a_dispatch_may_decide(kind, in_dispatch, may_decide):
    assert ApprovalActor(**actor(kind=kind, in_dispatch=in_dispatch)).may_decide is may_decide


@pytest.mark.parametrize("missing", ["kind", "in_dispatch", "principal_id"])
def test_actor_fields_have_no_defaults(missing):
    data = actor()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        ApprovalActor(**data)


@pytest.mark.parametrize("value", ["false", 0, None])
def test_in_dispatch_is_a_strict_boolean(value):
    with pytest.raises(ValidationError, match="in_dispatch"):
        ApprovalActor(**actor(in_dispatch=value))


def test_unknown_actor_kinds_are_refused():
    with pytest.raises(ValidationError, match="kind"):
        ApprovalActor(**actor(kind="admin"))


def test_create_request_carries_the_operation_and_its_owner():
    request = ApprovalCreateRequest(operation=OPERATION, actor=actor())
    assert request.operation == OPERATION
    assert request.actor.kind is ActorKind.USER


def test_create_request_refuses_an_actor_other_than_the_owner():
    with pytest.raises(ValidationError, match="actor must be the principal"):
        ApprovalCreateRequest(operation=OPERATION, actor=actor(principal_id="user-2"))


def test_requests_refuse_unknown_fields_such_as_a_status():
    with pytest.raises(ValidationError, match="status"):
        ApprovalDecisionRequest(approved=True, actor=actor(), status="approved")
    with pytest.raises(ValidationError, match="approval_id"):
        ApprovalCreateRequest(operation=OPERATION, actor=actor(), approval_id="apr-1")


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_approved_is_a_strict_boolean(value):
    with pytest.raises(ValidationError, match="approved"):
        ApprovalDecisionRequest(approved=value, actor=actor())
