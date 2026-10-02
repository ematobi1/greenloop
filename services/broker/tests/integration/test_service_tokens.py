"""Service tokens on Postgres: hashed at rest, constant-time compare, rotation,
revocation, audit, and a CLI that writes only the token to stdout (ADR 0009 rule 2)."""

import hmac
import logging

import pytest
from sqlalchemy import select, text
from tests.integration.pg import TEST_DATABASE_URL

from app import cli, service_tokens
from app.db.tables import audit_events
from app.db.tables import service_tokens as service_tokens_table

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


def stored_row(engine, token_id):
    with engine.connect() as connection:
        return (
            connection.execute(
                select(service_tokens_table).where(service_tokens_table.c.token_id == token_id)
            )
            .mappings()
            .one()
        )


def test_issue_stores_only_the_hash(engine, db_roles):
    token_id, token = service_tokens.issue(engine, "orchestrator")
    assert token.startswith("glsvc_") and len(token) > 40
    row = stored_row(engine, token_id)
    assert row["token_hash"] == service_tokens.hash_token(token) != token
    with db_roles.admin_engine.connect() as connection:
        dump = (
            connection.execute(text("SELECT row_to_json(t)::text FROM broker.service_tokens t"))
            .scalars()
            .all()
        )
        audit_text = (
            connection.execute(text("SELECT row_to_json(a)::text FROM broker.audit_events a"))
            .scalars()
            .all()
        )
    assert not any(token in line for line in dump + audit_text)


def test_each_issue_gives_a_different_token(engine):
    tokens = {service_tokens.issue(engine, "orchestrator")[1] for _ in range(5)}
    assert len(tokens) == 5


def test_authenticate_accepts_an_active_token(engine):
    token_id, token = service_tokens.issue(engine, "orchestrator")
    info = service_tokens.authenticate(engine, token)
    assert (info.token_id, info.name, info.revoked_at) == (token_id, "orchestrator", None)


@pytest.mark.parametrize(
    "presented", ["", "glsvc_", "glsvc_not-a-real-token", "Bearer glsvc_x", "x" * 10_000]
)
def test_authenticate_refuses_unknown_tokens(engine, presented):
    assert service_tokens.authenticate(engine, presented) is None


def test_authenticate_refuses_a_token_that_differs_by_one_character(engine):
    _, token = service_tokens.issue(engine, "orchestrator")
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert service_tokens.authenticate(engine, changed) is None


def test_authenticate_compares_hashes_in_constant_time(engine, monkeypatch):
    _, token = service_tokens.issue(engine, "orchestrator")
    calls = []
    original = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(service_tokens.hmac, "compare_digest", spy)
    assert service_tokens.authenticate(engine, token) is not None
    assert calls == [(service_tokens.hash_token(token), service_tokens.hash_token(token))]


def test_rotation_keeps_both_tokens_until_the_old_one_is_revoked(engine):
    old_id, old = service_tokens.issue(engine, "orchestrator")
    _, new = service_tokens.issue(engine, "orchestrator")
    assert service_tokens.authenticate(engine, old) is not None
    assert service_tokens.authenticate(engine, new) is not None
    assert service_tokens.revoke(engine, old_id) is True
    assert service_tokens.authenticate(engine, old) is None
    assert service_tokens.authenticate(engine, new) is not None


def test_revoke_is_audited_once_and_cannot_repeat(engine):
    token_id, _ = service_tokens.issue(engine, "orchestrator")
    assert service_tokens.revoke(engine, token_id) is True
    assert service_tokens.revoke(engine, token_id) is False
    assert service_tokens.revoke(engine, "svc-missing") is False
    with engine.connect() as connection:
        actions = (
            connection.execute(
                select(audit_events.c.action)
                .where(audit_events.c.resource_id == token_id)
                .order_by(audit_events.c.created_at)
            )
            .scalars()
            .all()
        )
    assert actions == ["service_token.issue", "service_token.revoke"]


def test_cli_writes_only_the_token_to_stdout(engine, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    assert cli.run(["issue-service-token", "--name", "orchestrator"], engine) == 0
    out, err = capsys.readouterr()
    token = out.strip()
    assert out == token + "\n"
    assert service_tokens.authenticate(engine, token) is not None
    assert token not in err
    assert token not in caplog.text
    assert "BROKER_SERVICE_TOKEN" in err


def test_cli_lists_and_revokes_without_showing_tokens(engine, capsys):
    token_id, token = service_tokens.issue(engine, "list-me")
    assert cli.run(["list-service-tokens"], engine) == 0
    listed = capsys.readouterr().out
    assert token_id in listed and "active" in listed
    assert token not in listed and service_tokens.hash_token(token) not in listed
    assert cli.run(["revoke-service-token", token_id], engine) == 0
    assert cli.run(["revoke-service-token", token_id], engine) == 1
    assert "no active service token" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["", "has space", "x" * 101])
def test_cli_rejects_bad_names(engine, name):
    with pytest.raises(SystemExit):
        cli.run(["issue-service-token", "--name", name], engine)
