"""verify_database against real Postgres: each broken state is caught and named, and the
healthy migrated schema passes. Every test restores what it changed."""

import pytest
from sqlalchemy import text
from tests.integration.pg import TEST_DATABASE_URL

from app.db.startup_check import APPEND_ONLY_TRIGGERS, DatabaseStartupError, verify_database

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


def _admin(db_roles, sql: str, **params: str) -> None:
    with db_roles.admin_engine.begin() as connection:
        connection.execute(text(sql), params)


def _version(db_roles) -> str:
    with db_roles.admin_engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM broker.alembic_version")
        ).scalar_one()


def test_a_migrated_schema_owned_by_the_role_passes(engine):
    verify_database(engine)


def test_a_table_owned_by_another_role_is_named(engine, db_roles):
    _admin(db_roles, "CREATE TABLE broker.zz_startup_foreign (id int)")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "DROP TABLE broker.zz_startup_foreign")
    message = str(caught.value)
    admin_role = db_roles.admin_engine.url.username
    assert f"broker.zz_startup_foreign is owned by {admin_role}, not greenloop_broker." in message
    assert db_roles.broker_password not in message


def test_a_schema_not_at_head_is_caught(engine, db_roles):
    head = _version(db_roles)
    _admin(db_roles, "UPDATE broker.alembic_version SET version_num = 'zz_not_a_revision'")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "UPDATE broker.alembic_version SET version_num = :v", v=head)
    assert f"Migrations are at zz_not_a_revision, not head {head}." in str(caught.value)


def test_an_unmigrated_schema_is_caught(engine, db_roles):
    _admin(db_roles, "ALTER TABLE broker.alembic_version RENAME TO zz_alembic_version_hidden")
    try:
        with pytest.raises(DatabaseStartupError, match="Migrations have not run"):
            verify_database(engine)
    finally:
        _admin(db_roles, "ALTER TABLE broker.zz_alembic_version_hidden RENAME TO alembic_version")


@pytest.mark.parametrize("trigger", APPEND_ONLY_TRIGGERS)
@pytest.mark.parametrize("mode", ["DISABLE TRIGGER", "ENABLE REPLICA TRIGGER"])
def test_an_append_only_trigger_that_does_not_fire_is_caught(engine, db_roles, trigger, mode):
    _admin(db_roles, f"ALTER TABLE broker.audit_events {mode} {trigger}")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, f"ALTER TABLE broker.audit_events ENABLE TRIGGER {trigger}")
    assert f"broker.audit_events.{trigger} is not enabled." in str(caught.value)
    verify_database(engine)


def test_a_dropped_append_only_trigger_is_caught(engine, db_roles):
    _admin(db_roles, "DROP TRIGGER audit_events_no_truncate ON broker.audit_events")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(
            db_roles,
            "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON broker.audit_events"
            " FOR EACH STATEMENT EXECUTE FUNCTION broker.audit_events_append_only()",
        )
    assert "broker.audit_events.audit_events_no_truncate is missing." in str(caught.value)
    verify_database(engine)


def test_a_trigger_calling_another_function_counts_as_missing(engine, db_roles):
    _admin(
        db_roles,
        "CREATE FUNCTION broker.zz_allow_all() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RETURN NULL; END; $$;"
        " DROP TRIGGER audit_events_no_truncate ON broker.audit_events;"
        " CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON broker.audit_events"
        " FOR EACH STATEMENT EXECUTE FUNCTION broker.zz_allow_all()",
    )
    try:
        with pytest.raises(DatabaseStartupError, match="audit_events_no_truncate is missing"):
            verify_database(engine)
    finally:
        _admin(
            db_roles,
            "DROP TRIGGER audit_events_no_truncate ON broker.audit_events;"
            " DROP FUNCTION broker.zz_allow_all();"
            " CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON broker.audit_events"
            " FOR EACH STATEMENT EXECUTE FUNCTION broker.audit_events_append_only()",
        )
    verify_database(engine)
