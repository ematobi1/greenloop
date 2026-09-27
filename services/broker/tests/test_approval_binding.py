import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.approval_binding import (
    ApprovalAlreadyConsumedError,
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    InMemoryApprovalStore,
    canonicalize,
    operation_hash,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=10)


@pytest.fixture
def store() -> InMemoryApprovalStore:
    return InMemoryApprovalStore()


class TestCanonicalHash:
    def test_argument_order_does_not_change_hash(self, permission):
        first = permission(repo="greenloop", title="Bug")
        second = permission(title="Bug", repo="greenloop")
        assert operation_hash(first) == operation_hash(second)

    def test_canonical_form_is_compact_sorted_utf8(self, permission):
        canonical = canonicalize(permission(title="café"))
        assert b" " not in canonical.replace(b"create_issue", b"")
        assert "café".encode() in canonical
        assert canonical.index(b'"arguments"') < canonical.index(b'"tool"')

    @pytest.mark.parametrize(
        "change",
        [
            {"title": "Bug!"},
            {"title": "Bug", "labels": ["x"]},
            {"repo": "other"},
        ],
    )
    def test_any_argument_change_changes_hash(self, permission, change):
        original = permission(repo="greenloop", title="Bug")
        changed = permission(**{"repo": "greenloop", "title": "Bug", **change})
        assert operation_hash(original) != operation_hash(changed)

    def test_principal_and_operation_are_bound(self, permission):
        base = operation_hash(permission())
        assert base != operation_hash(permission(principal_id="user-2"))
        assert base != operation_hash(permission(operation="create_pull_request"))
        assert base != operation_hash(permission(consequence="send"))

    def test_hash_is_lowercase_sha256_hex(self, permission):
        digest = operation_hash(permission())
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)


class TestSingleUse:
    def test_exact_operation_consumes_once(self, store, permission):
        granted = store.grant("appr-1", permission(), LATER)
        assert store.consume("appr-1", permission(), now=NOW) == granted
        with pytest.raises(ApprovalAlreadyConsumedError):
            store.consume("appr-1", permission(), now=NOW)

    def test_changed_operation_is_refused_and_does_not_burn_approval(self, store, permission):
        store.grant("appr-1", permission(title="Bug"), LATER)
        with pytest.raises(ApprovalMismatchError):
            store.consume("appr-1", permission(title="Different"), now=NOW)
        store.consume("appr-1", permission(title="Bug"), now=NOW)

    def test_other_principal_cannot_use_approval(self, store, permission):
        store.grant("appr-1", permission(), LATER)
        with pytest.raises(ApprovalMismatchError):
            store.consume("appr-1", permission(principal_id="user-2"), now=NOW)

    def test_expired_approval_is_refused(self, store, permission):
        store.grant("appr-1", permission(), NOW)
        with pytest.raises(ApprovalExpiredError):
            store.consume("appr-1", permission(), now=NOW)

    def test_unknown_approval_is_refused(self, store, permission):
        with pytest.raises(ApprovalNotFoundError):
            store.consume("missing", permission(), now=NOW)

    def test_approval_ids_cannot_be_reissued(self, store, permission):
        store.grant("appr-1", permission(), LATER)
        with pytest.raises(ValueError, match="already exists"):
            store.grant("appr-1", permission(title="Other"), LATER)

    def test_concurrent_consumers_only_one_wins(self, store, permission):
        store.grant("appr-1", permission(), LATER)
        barrier = threading.Barrier(16)
        outcomes: list[str] = []

        def attempt() -> None:
            barrier.wait()
            try:
                store.consume("appr-1", permission(), now=NOW)
                outcomes.append("ok")
            except ApprovalAlreadyConsumedError:
                outcomes.append("consumed")

        threads = [threading.Thread(target=attempt) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert outcomes.count("ok") == 1
        assert outcomes.count("consumed") == 15
