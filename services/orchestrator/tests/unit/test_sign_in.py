"""Web sign-in (ADR 0012): argon2id hashes, sessions that authenticate like tokens,
identical failures for unknown users and wrong passwords, per-username lockout that
works for unknown names too, sign-out of one or every session, and nothing secret in
logs."""

from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import cli
from app.api.v1.sessions import SignInLimiter
from app.core import accounts
from app.core.redaction import Redactor
from app.db.models import (
    AuditRecordRow,
    LoginThrottleRow,
    PrincipalRow,
    UserCredentialRow,
    UserSessionRow,
)

PASSWORD = "correct horse battery staple"


@pytest.fixture
def user(session_factory, issue_token):
    issue_token("user-1")
    with session_factory() as session:
        accounts.create_user(session, "user-1", "Alice", PASSWORD)
        session.commit()
    return "alice"


def _sign_in(client, username="alice", password=PASSWORD):
    return client.post("/v1/sessions", json={"username": username, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_passwords_are_stored_only_as_argon2id_hashes(session_factory, user):
    with session_factory() as session:
        row = session.get(UserCredentialRow, "user-1")
    assert row.username == "alice"
    assert row.password_hash.startswith("$argon2id$")
    assert PASSWORD not in row.password_hash


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("ab", PASSWORD, "Usernames"),
        ("has space", PASSWORD, "Usernames"),
        ("-leading", PASSWORD, "Usernames"),
        ("bob", "short", "Passwords"),
        ("bob", "x" * 257, "Passwords"),
    ],
)
def test_bad_usernames_and_passwords_are_refused(
    session_factory, issue_token, username, password, message
):
    issue_token("user-2")
    with session_factory() as session, pytest.raises(accounts.AccountError, match=message):
        accounts.create_user(session, "user-2", username, password)


def test_one_username_per_principal_and_no_duplicates(session_factory, issue_token, user):
    issue_token("user-2")
    with session_factory() as session:
        with pytest.raises(accounts.AccountError, match="already has"):
            accounts.create_user(session, "user-1", "other", PASSWORD)
        with pytest.raises(accounts.AccountError, match="taken"):
            accounts.create_user(session, "user-2", "ALICE", PASSWORD)
        with pytest.raises(accounts.AccountError, match="No such principal"):
            accounts.create_user(session, "ghost", "ghost", PASSWORD)


def test_a_session_token_authenticates_and_only_its_hash_is_stored(client, session_factory, user):
    response = _sign_in(client, username="  ALICE ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["session_token"].startswith("gls_")
    assert body["principal_id"] == "user-1"
    assert (
        client.get("/v1/conversations", headers=_bearer(body["session_token"])).status_code == 200
    )
    with session_factory() as session:
        row = session.scalars(select(UserSessionRow)).one()
        actions = session.scalars(select(AuditRecordRow.action)).all()
    assert row.token_hash == accounts.hash_session_token(body["session_token"])
    assert body["session_token"] not in row.token_hash
    assert "auth.sign_in" in actions


def test_unknown_users_and_wrong_passwords_get_the_same_answer(client, user):
    wrong = _sign_in(client, password="not the password at all")
    unknown = _sign_in(client, username="mallory")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.parametrize("username", ["alice", "nobody-here"])
def test_five_failures_lock_the_username_known_or_not(client, session_factory, user, username):
    for _ in range(accounts.MAX_FAILURES):
        assert _sign_in(client, username=username, password="wrong password!!").status_code == 401
    locked = _sign_in(client, username=username)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "SIGN_IN_THROTTLED"
    assert 0 < int(locked.headers["Retry-After"]) <= accounts.LOCKOUT.total_seconds() + 1

    with session_factory() as session:
        session.get(LoginThrottleRow, username).locked_until = datetime.now(UTC) - timedelta(
            seconds=1
        )
        session.commit()
    if username == "alice":
        assert _sign_in(client).status_code == 201


def test_a_success_resets_the_failure_count(client, session_factory, user):
    for _ in range(accounts.MAX_FAILURES - 1):
        _sign_in(client, password="wrong password!!")
    assert _sign_in(client).status_code == 201
    with session_factory() as session:
        assert session.get(LoginThrottleRow, "alice").failures == 0


def test_disabled_principals_can_not_sign_in_or_use_old_sessions(client, session_factory, user):
    token = _sign_in(client).json()["session_token"]
    with session_factory() as session:
        session.get(PrincipalRow, "user-1").disabled_at = datetime.now(UTC)
        session.commit()
    assert client.get("/v1/conversations", headers=_bearer(token)).status_code == 401
    assert _sign_in(client).status_code == 401


def test_expired_sessions_are_rejected(client, session_factory, user):
    token = _sign_in(client).json()["session_token"]
    with session_factory() as session:
        session.scalars(select(UserSessionRow)).one().expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        session.commit()
    assert client.get("/v1/conversations", headers=_bearer(token)).status_code == 401


def test_sign_out_ends_only_this_session(client, user):
    first = _sign_in(client).json()["session_token"]
    second = _sign_in(client).json()["session_token"]
    assert client.delete("/v1/sessions/current", headers=_bearer(first)).status_code == 204
    assert client.get("/v1/conversations", headers=_bearer(first)).status_code == 401
    assert client.get("/v1/conversations", headers=_bearer(second)).status_code == 200


def test_sign_out_everywhere_ends_every_session(client, user):
    first = _sign_in(client).json()["session_token"]
    second = _sign_in(client).json()["session_token"]
    assert client.delete("/v1/sessions", headers=_bearer(first)).status_code == 204
    for token in (first, second):
        assert client.get("/v1/conversations", headers=_bearer(token)).status_code == 401


def test_api_tokens_can_not_use_session_sign_out(client, issue_token):
    token = issue_token("user-1")
    for path in ("/v1/sessions/current", "/v1/sessions"):
        response = client.delete(path, headers=_bearer(token))
        assert (response.status_code, response.json()["error"]["code"]) == (409, "NOT_A_SESSION")
    assert client.get("/v1/conversations", headers=_bearer(token)).status_code == 200


def test_changing_the_password_signs_out_everywhere(client, session_factory, user):
    token = _sign_in(client).json()["session_token"]
    with session_factory() as session:
        assert accounts.set_password(session, "user-1", "a brand new password") == 1
        session.commit()
    assert client.get("/v1/conversations", headers=_bearer(token)).status_code == 401
    assert _sign_in(client).status_code == 401
    assert _sign_in(client, password="a brand new password").status_code == 201


def test_a_flood_of_failures_is_throttled_but_never_locks_out_valid_users(client, user):
    client.app.state.sign_in_limiter = SignInLimiter(limit=3, window=60)
    statuses = [_sign_in(client, username=f"user{i}x").status_code for i in range(5)]
    assert statuses == [401, 401, 401, 429, 429]
    assert _sign_in(client).status_code == 201


def test_verifications_are_capped(client, user):
    limiter = SignInLimiter(concurrency=1)
    client.app.state.sign_in_limiter = limiter
    assert limiter.verifications.acquire(blocking=False)
    try:
        assert not limiter.verifications.acquire(blocking=False)
    finally:
        limiter.verifications.release()
    assert _sign_in(client).status_code == 201


def test_outdated_hashes_are_upgraded_on_sign_in(client, session_factory, user):
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    with session_factory() as session:
        session.get(UserCredentialRow, "user-1").password_hash = weak
        session.commit()
    assert _sign_in(client).status_code == 201
    with session_factory() as session:
        after = session.get(UserCredentialRow, "user-1").password_hash
    assert after != weak
    assert not PasswordHasher().check_needs_rehash(after)


@pytest.mark.parametrize(
    "body", [{}, {"username": "alice"}, {"username": "a", "password": "b", "extra": 1}]
)
def test_malformed_sign_in_bodies_are_rejected(client, body):
    assert client.post("/v1/sessions", json=body).status_code == 422


def test_sign_in_never_logs_the_password_or_token(client, user, capsys, caplog):
    token = _sign_in(client).json()["session_token"]
    _sign_in(client, password="wrong password!!")
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    assert PASSWORD not in logs and "wrong password!!" not in logs
    assert token not in logs


def test_greenloop_tokens_are_redacted():
    text = "token gls_" + "a" * 43 + " and glt_" + "b" * 43
    assert "gls_aaaa" not in Redactor().redact(text)
    assert "glt_bbbb" not in Redactor().redact(text)


def test_cli_creates_users_and_changes_passwords(session_factory, issue_token, monkeypatch, capsys):
    issue_token("user-2")
    monkeypatch.setenv(cli.NEW_PASSWORD_VARIABLE, PASSWORD)
    assert cli.run(["create-user", "user-2", "Bob"], session_factory) == 0
    assert "sign in as bob" in capsys.readouterr().out
    monkeypatch.setenv(cli.NEW_PASSWORD_VARIABLE, "another long password")
    assert cli.run(["set-password", "user-2"], session_factory) == 0
    assert cli.run(["revoke-sessions", "user-2"], session_factory) == 0
    assert cli.run(["create-user", "user-2", "bob2"], session_factory) == 1
    assert "already has" in capsys.readouterr().err


def test_cli_prompts_twice_and_refuses_a_mismatch(monkeypatch):
    monkeypatch.delenv(cli.NEW_PASSWORD_VARIABLE, raising=False)
    answers = iter(["first password!!", "second password!"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    with pytest.raises(accounts.AccountError, match="don't match"):
        cli.read_new_password()


def test_cli_unlocks_a_locked_username(client, session_factory, user, capsys):
    for _ in range(accounts.MAX_FAILURES):
        _sign_in(client, password="wrong password!!")
    assert _sign_in(client).status_code == 429
    assert cli.run(["unlock-user", "ALICE"], session_factory) == 0
    assert "Unlocked." in capsys.readouterr().out
    assert _sign_in(client).status_code == 201
    assert cli.run(["unlock-user", "alice"], session_factory) == 0
    assert "not locked" in capsys.readouterr().out


def test_cli_revoke_sessions_refuses_an_unknown_principal(session_factory, capsys):
    assert cli.run(["revoke-sessions", "ghost"], session_factory) == 1
    assert "No such principal" in capsys.readouterr().err


def test_stale_throttle_rows_are_pruned_on_a_successful_sign_in(client, session_factory, user):
    with session_factory() as session:
        session.add(LoginThrottleRow(username="old-name", failures=0))
        session.add(LoginThrottleRow(username="still-failing", failures=2))
        session.commit()
        for row in session.scalars(select(LoginThrottleRow)):
            row.updated_at = datetime.now(UTC) - timedelta(days=2)
        session.commit()
    assert _sign_in(client).status_code == 201
    with session_factory() as session:
        names = set(session.scalars(select(LoginThrottleRow.username)))
    assert "old-name" not in names
    assert "still-failing" in names
