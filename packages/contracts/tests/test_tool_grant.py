from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from greenloop_contracts import ToolGrant, ToolPermission

BEFORE_EXPIRY = datetime(2026, 9, 28, tzinfo=UTC)
AFTER_EXPIRY = datetime(2026, 10, 2, tzinfo=UTC)


def grant(payloads, **overrides) -> ToolGrant:
    return ToolGrant.model_validate({**payloads["ToolGrant"], **overrides})


def permission(payloads, **overrides) -> ToolPermission:
    return ToolPermission.model_validate({**payloads["ToolPermission"], **overrides})


def test_accepts_owner_granted_permission(payloads):
    assert grant(payloads).granted_by == "owner"


@pytest.mark.parametrize("granted_by", ["agent-1", "system", "AI", "", None, "Owner"])
def test_rejects_any_grantor_other_than_owner(payloads, granted_by):
    with pytest.raises(ValidationError):
        grant(payloads, granted_by=granted_by)


def test_rejects_empty_actions_list(payloads):
    with pytest.raises(ValidationError):
        grant(payloads, actions=[])


def test_rejects_duplicate_actions(payloads):
    with pytest.raises(ValidationError, match="unique"):
        grant(payloads, actions=["create_issue", "create_issue"])


def test_expiry_must_be_after_grant(payloads):
    with pytest.raises(ValidationError, match="expires_at"):
        grant(payloads, expires_at="2026-09-27T12:00:00Z")


def test_grant_without_expiry_is_always_active(payloads):
    assert grant(payloads).is_active(AFTER_EXPIRY)


def test_grant_expires(payloads):
    expiring = grant(payloads, expires_at="2026-10-01T00:00:00Z")
    assert expiring.is_active(BEFORE_EXPIRY)
    assert not expiring.is_active(AFTER_EXPIRY)


class TestCovers:
    def test_covers_a_matching_request(self, payloads):
        assert grant(payloads).covers(permission(payloads), BEFORE_EXPIRY)

    @pytest.mark.parametrize(
        "change",
        [
            {"operation": "merge_pull_request"},
            {"tool": "slack"},
            {"agent_id": "research-agent"},
            {"agent_id": None},
            {"principal_id": "user-2"},
        ],
    )
    def test_does_not_cover_a_different_request(self, payloads, change):
        assert not grant(payloads).covers(permission(payloads, **change), BEFORE_EXPIRY)

    def test_does_not_cover_after_expiry(self, payloads):
        expiring = grant(payloads, expires_at="2026-10-01T00:00:00Z")
        assert not expiring.covers(permission(payloads), AFTER_EXPIRY)
