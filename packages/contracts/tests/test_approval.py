from datetime import timedelta

import pytest
from pydantic import ValidationError

from greenloop_contracts import (
    DEFAULT_APPROVAL_TTL,
    Approval,
    ApprovalStatus,
    ToolPermission,
    operation_hash,
)

DECIDED = {"decided_by": "user-1", "decided_at": "2026-09-27T12:01:00Z"}


def _approval(payloads, **changes):
    return Approval.model_validate({**payloads["Approval"], **changes})


def test_a_new_approval_is_pending(payloads):
    approval = _approval(payloads)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.operation_hash == operation_hash(approval.operation)


def test_the_default_lifetime_is_fifteen_minutes():
    assert timedelta(minutes=15) == DEFAULT_APPROVAL_TTL


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "approved", **DECIDED},
        {"status": "rejected", **DECIDED},
        {"status": "consumed", **DECIDED, "consumed_at": "2026-09-27T12:02:00Z"},
        {"status": "expired"},
        {"status": "expired", **DECIDED},
    ],
)
def test_valid_status_and_timestamp_combinations(payloads, changes):
    assert _approval(payloads, **changes).status == changes["status"]


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending", **DECIDED},
        {"status": "approved"},
        {"status": "rejected"},
        {"status": "consumed", **DECIDED},
        {"status": "consumed", "consumed_at": "2026-09-27T12:02:00Z"},
        {"status": "approved", **DECIDED, "consumed_at": "2026-09-27T12:02:00Z"},
        {"status": "expired", "consumed_at": "2026-09-27T12:02:00Z"},
        {"status": "approved", "decided_by": "user-1"},
        {"status": "approved", "decided_at": "2026-09-27T12:01:00Z"},
        {"status": "approved", "decided_by": "user-1", "decided_at": "2026-09-27T11:00:00Z"},
        {"status": "consumed", **DECIDED, "consumed_at": "2026-09-27T12:00:30Z"},
        {"status": "made-up"},
    ],
)
def test_inconsistent_status_and_timestamps_are_refused(payloads, changes):
    with pytest.raises(ValidationError):
        _approval(payloads, **changes)


def test_the_hash_must_match_the_operation(payloads):
    with pytest.raises(ValidationError, match="operation_hash"):
        _approval(payloads, operation_hash="b" * 64)


def test_changing_the_operation_without_the_hash_is_refused(payloads):
    operation = {**payloads["Approval"]["operation"], "arguments": {"repo": "other"}}
    with pytest.raises(ValidationError, match="operation_hash"):
        _approval(payloads, operation=operation)


def test_the_operation_must_belong_to_the_principal(payloads):
    operation = ToolPermission.model_validate(
        {**payloads["Approval"]["operation"], "principal_id": "user-2"}
    )
    with pytest.raises(ValidationError, match="principal"):
        _approval(payloads, operation=operation, operation_hash=operation_hash(operation))


@pytest.mark.parametrize("expires_at", ["2026-09-27T12:00:00Z", "2026-09-27T11:59:00Z"])
def test_it_must_expire_after_it_is_created(payloads, expires_at):
    with pytest.raises(ValidationError, match="expires_at"):
        _approval(payloads, expires_at=expires_at)


@pytest.mark.parametrize("summary", ["", "   ", "x" * 501])
def test_the_summary_is_a_short_safe_message(payloads, summary):
    with pytest.raises(ValidationError):
        _approval(payloads, summary=summary)


def test_approvals_are_immutable(payloads):
    approval = _approval(payloads)
    with pytest.raises(ValidationError):
        approval.status = ApprovalStatus.APPROVED
