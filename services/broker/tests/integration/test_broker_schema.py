"""The broker schema: migration matches the tables, lives only in broker, audit_events
is append-only, and the orchestrator role cannot touch any of it (ADR 0009 rules 1, 10)."""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, delete, inspect, literal_column, select, table, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from tests.integration.pg import TEST_DATABASE_URL, alembic_command

from app import audit
from app.db.tables import SCHEMA, metadata
from greenloop_contracts import AuditOutcome

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

BROKER_TABLES = {"approvals", "audit_events", "service_tokens", "alembic_version"}


def test_tables_match_the_migration(engine, db_roles):
    # With broker as the default schema Alembic reflects its tables as schema None,
    # which never matches schema="broker" in the metadata. The dialect caches the
    # default schema on first connect, so this engine starts outside broker.
    outside = create_engine(
        db_roles.url("greenloop_broker"), connect_args={"options": "-c search_path=pg_catalog"}
    )
    try:
        with outside.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_schemas": True,
                    "include_name": lambda name, type_, parent: (
                        name == SCHEMA if type_ == "schema" else name != "alembic_version"
                    ),
                },
            )
            assert compare_metadata(context, metadata) == []
    finally:
        outside.dispose()


def test_everything_lives_in_the_broker_schema(engine, db_roles):
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == BROKER_TABLES
    with db_roles.admin_engine.connect() as connection:
        owners = (
            connection.execute(
                text(
                    "SELECT DISTINCT relowner::regrole::text FROM pg_class"
                    " WHERE relnamespace = 'broker'::regnamespace"
                )
            )
            .scalars()
            .all()
        )
    assert owners == ["greenloop_broker"]


def test_downgrade_removes_everything_and_upgrade_restores_it(engine):
    alembic_command(engine, "downgrade", "base")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    alembic_command(engine, "upgrade", "head")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == BROKER_TABLES


@pytest.fixture
def audit_id(engine) -> str:
    with engine.begin() as connection:
        return audit.record(
            connection,
            principal_id="user-1",
            actor="test",
            action="approval.create",
            outcome=AuditOutcome.DENIED,
            correlation_id=f"corr-{uuid.uuid4().hex}",
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE broker.audit_events SET actor = 'tampered' WHERE audit_id = :id",
        "DELETE FROM broker.audit_events WHERE audit_id = :id",
        "TRUNCATE broker.audit_events",
    ],
)
def test_audit_events_are_append_only(engine, audit_id, statement):
    with engine.begin() as connection, pytest.raises(DBAPIError, match="append-only"):
        connection.execute(text(statement), {"id": audit_id})
    with engine.connect() as connection:
        actor = connection.scalar(
            text("SELECT actor FROM broker.audit_events WHERE audit_id = :id"), {"id": audit_id}
        )
    assert actor == "test"


def test_audit_events_use_the_database_clock(engine, audit_id):
    with engine.connect() as connection:
        lag = connection.scalar(
            text("SELECT now() - occurred_at FROM broker.audit_events WHERE audit_id = :id"),
            {"id": audit_id},
        )
    assert lag.total_seconds() >= 0


@pytest.mark.parametrize("name", sorted(BROKER_TABLES))
def test_the_orchestrator_role_cannot_read_or_write_broker_tables(engine, db_roles, name):
    orchestrator = create_engine(db_roles.url("greenloop_orchestrator"))
    try:
        with orchestrator.connect() as connection:
            with pytest.raises(ProgrammingError, match="permission denied for schema broker"):
                connection.execute(
                    select(literal_column("1")).select_from(table(name, schema=SCHEMA))
                )
            connection.rollback()
            with pytest.raises(ProgrammingError, match="permission denied for schema broker"):
                connection.execute(delete(table(name, schema=SCHEMA)))
    finally:
        orchestrator.dispose()
