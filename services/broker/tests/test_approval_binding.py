import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.approval_binding import (
    ApprovalAlreadyConsumedError,
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    InMemoryApprovalStore,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=10)


@pytest.fixture
def store() -> InMemoryApprovalStore:
    return InMemoryApprovalStore()


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
