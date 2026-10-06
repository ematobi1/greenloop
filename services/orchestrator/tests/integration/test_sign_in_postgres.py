"""Sign-in on real Postgres: concurrent wrong passwords are all counted (the throttle row
is locked FOR UPDATE), so racing requests can't slip past the lockout."""

import threading
import uuid

import pytest
from tests.integration.pg import TEST_DATABASE_URL

from app.core import accounts, tokens
from app.db.models import LoginThrottleRow

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

PASSWORD = "correct horse battery staple"


def test_parallel_failures_all_count_toward_the_lockout(pg_session_factory):
    principal_id = f"it-{uuid.uuid4().hex[:12]}"
    username = f"race{uuid.uuid4().hex[:8]}"
    with pg_session_factory() as session:
        tokens.create_principal(session, principal_id, "Race")
        accounts.create_user(session, principal_id, username, PASSWORD)
        session.commit()

    outcomes: list[str] = []
    barrier = threading.Barrier(accounts.MAX_FAILURES * 2)

    def attempt() -> None:
        barrier.wait()
        with pg_session_factory() as session:
            try:
                accounts.sign_in(session, username, "wrong password!!", "it")
            except accounts.InvalidCredentialsError:
                outcomes.append("invalid")
            except accounts.LoginThrottledError:
                outcomes.append("throttled")
            session.commit()

    threads = [threading.Thread(target=attempt) for _ in range(accounts.MAX_FAILURES * 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("invalid") == accounts.MAX_FAILURES
    assert outcomes.count("throttled") == accounts.MAX_FAILURES
    with pg_session_factory() as session:
        assert session.get(LoginThrottleRow, username).locked_until is not None
        with pytest.raises(accounts.LoginThrottledError):
            accounts.sign_in(session, username, PASSWORD, "it")
