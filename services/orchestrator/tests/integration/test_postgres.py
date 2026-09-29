"""Postgres-only behavior: the real migration, append-only triggers, JSONB, end-to-end auth.

Skipped unless TEST_DATABASE_URL points at a disposable database. Every run
downgrades to base and upgrades to head, so never point it at real data.
"""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.integration.pg import TEST_DATABASE_URL, alembic_command

from app.audit import recorder
from app.core import tokens
from app.core.config import Settings
from app.db.models import Base
from app.db.session import make_engine
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


def test_models_match_the_migration(engine):
    with engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diffs == []


def test_details_column_is_jsonb(engine):
    columns = {column["name"]: column for column in inspect(engine).get_columns("audit_records")}
    assert columns["details"]["type"].__class__.__name__ == "JSONB"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_records SET action = 'tampered' WHERE principal_id = :principal_id",
        "DELETE FROM audit_records WHERE principal_id = :principal_id",
        "TRUNCATE audit_records",
    ],
)
def test_audit_records_are_append_only(engine, principal_id, statement):
    with engine.begin() as connection, pytest.raises(DBAPIError, match="append-only"):
        connection.execute(text(statement), {"principal_id": principal_id})
    with engine.connect() as connection:
        count = connection.scalar(
            text("SELECT count(*) FROM audit_records WHERE principal_id = :p"),
            {"p": principal_id},
        )
    assert count == 1


def test_unknown_outcome_is_rejected_by_the_check_constraint(engine, principal_id):
    with engine.begin() as connection, pytest.raises(IntegrityError, match="ck_audit_records"):
        connection.execute(
            text(
                "INSERT INTO audit_records (audit_id, principal_id, actor, action, resource_type,"
                " outcome, correlation_id, details, occurred_at) VALUES (:id, :p, 'a', 'b', 'c',"
                " 'maybe', 'req', '{}'::jsonb, now())"
            ),
            {"id": f"aud-{uuid.uuid4().hex}", "p": principal_id},
        )


def test_audit_for_unknown_principal_is_rejected(pg_session_factory, make_audit):
    with pg_session_factory() as session, pytest.raises(IntegrityError):
        recorder.record(session, make_audit("a-orphan", principal_id="nobody-here"))
        session.commit()


def test_end_to_end_token_auth_and_audit_listing(pg_session_factory, principal_id, make_audit):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        recorder.record(session, make_audit(f"a-{uuid.uuid4().hex[:8]}", principal_id=principal_id))
        session.commit()
    settings = Settings(_env_file=None, environment="test", allowed_hosts=["testserver"])
    app = create_app(settings)
    app.state.session_factory = pg_session_factory
    client = TestClient(app)

    assert client.get("/v1/health").json() == {"status": "ok", "checks": {"database": "ok"}}
    assert client.get("/v1/audit-records").status_code == 401
    response = client.get("/v1/audit-records", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 3
    assert {item["principal_id"] for item in body["data"]} == {principal_id}
    assert {item["action"] for item in body["data"]} == {
        "principal.create",
        "token.issue",
        "memory.create",
    }


def test_statement_timeout_is_applied_by_make_engine():
    settings = Settings(_env_file=None, database_url=TEST_DATABASE_URL)
    with make_engine(settings).connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "10s"


def test_downgrade_removes_everything_and_upgrade_restores_it(engine):
    alembic_command(engine, "downgrade", "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    alembic_command(engine, "upgrade", "head")
    assert {"principals", "api_tokens", "audit_records"} <= set(inspect(engine).get_table_names())


def test_0003_backfills_existing_principals_as_user_and_constrains_role(engine):
    alembic_command(engine, "downgrade", "0002")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO principals (principal_id, display_name)"
                    " VALUES ('pre-0003', 'Existing')"
                )
            )
        alembic_command(engine, "upgrade", "0003")
        with engine.connect() as connection:
            role = connection.scalar(
                text("SELECT role FROM principals WHERE principal_id = 'pre-0003'")
            )
        assert role == "user"
        column = next(c for c in inspect(engine).get_columns("principals") if c["name"] == "role")
        assert column["nullable"] is False
        for bad_role, error in (("admin", "ck_principals_role"), (None, "not-null")):
            with engine.begin() as connection, pytest.raises(IntegrityError, match=error):
                connection.execute(
                    text(
                        "INSERT INTO principals (principal_id, display_name, role)"
                        " VALUES (:id, 'Bad', :role)"
                    ),
                    {"id": f"bad-{uuid.uuid4().hex[:8]}", "role": bad_role},
                )
    finally:
        alembic_command(engine, "upgrade", "head")
