"""verify_database against real Postgres: each broken state is caught and named, and the
healthy migrated schema passes. Every test restores what it changed."""

import pytest
from sqlalchemy import text
from tests.integration.pg import TEST_DATABASE_URL

from app.db.startup_check import (
    APPEND_ONLY_TRIGGERS,
    DatabaseStartupError,
    schema_problems,
    verify_database,
)

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


def test_a_database_ahead_of_the_image_says_rebuild(engine, db_roles):
    head = _version(db_roles)
    _admin(db_roles, "UPDATE broker.alembic_version SET version_num = 'zz_from_a_newer_image'")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "UPDATE broker.alembic_version SET version_num = :v", v=head)
    message = str(caught.value)
    assert f"zz_from_a_newer_image, which this image doesn't know (its head is {head})" in message
    assert "dev.ps1 -Service stack" in message
    assert "alembic upgrade" not in message


def test_a_missing_schema_is_reported_not_raised(engine):
    with engine.connect() as connection:
        assert schema_problems(connection, "zz_no_such_schema") == [
            "Schema zz_no_such_schema does not exist."
        ]
        assert schema_problems(connection, "broker") == []


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
    assert "has been changed" not in str(caught.value)
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


RESTORE_TRUNCATE = (
    "DROP TRIGGER IF EXISTS audit_events_no_truncate ON broker.audit_events;"
    " CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON broker.audit_events"
    " FOR EACH STATEMENT EXECUTE FUNCTION broker.audit_events_append_only()"
)
RESTORE_UPDATE_DELETE = (
    "DROP TRIGGER IF EXISTS audit_events_no_update_delete ON broker.audit_events;"
    " CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE"
    " ON broker.audit_events FOR EACH ROW EXECUTE FUNCTION broker.audit_events_append_only()"
)


T = "ON broker.audit_events"


@pytest.mark.parametrize(
    ("trigger", "clause", "restore"),
    [
        ("audit_events_no_update_delete", f"BEFORE INSERT {T} FOR EACH ROW", RESTORE_UPDATE_DELETE),
        (
            "audit_events_no_update_delete",
            f"AFTER UPDATE OR DELETE {T} FOR EACH ROW",
            RESTORE_UPDATE_DELETE,
        ),
        (
            "audit_events_no_update_delete",
            f"BEFORE UPDATE OR DELETE {T} FOR EACH STATEMENT",
            RESTORE_UPDATE_DELETE,
        ),
        (
            "audit_events_no_update_delete",
            f"BEFORE UPDATE OF action OR DELETE {T} FOR EACH ROW",
            RESTORE_UPDATE_DELETE,
        ),
        (
            "audit_events_no_update_delete",
            f"BEFORE UPDATE OR DELETE {T} FOR EACH ROW WHEN (false)",
            RESTORE_UPDATE_DELETE,
        ),
        (
            "audit_events_no_truncate",
            f"BEFORE TRUNCATE OR INSERT {T} FOR EACH STATEMENT",
            RESTORE_TRUNCATE,
        ),
        ("audit_events_no_truncate", f"AFTER TRUNCATE {T} FOR EACH STATEMENT", RESTORE_TRUNCATE),
    ],
)
def test_a_rewritten_trigger_is_caught(engine, db_roles, trigger, clause, restore):
    _admin(
        db_roles,
        f"DROP TRIGGER {trigger} {T}; CREATE TRIGGER {trigger} {clause}"
        " EXECUTE FUNCTION broker.audit_events_append_only()",
    )
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, restore)
    assert f"broker.audit_events.{trigger} has been changed" in str(caught.value)
    verify_database(engine)


def test_a_rewritten_function_body_is_caught(engine, db_roles):
    with db_roles.admin_engine.connect() as connection:
        original = connection.execute(
            text("SELECT pg_get_functiondef('broker.audit_events_append_only()'::regprocedure)")
        ).scalar_one()
    _admin(
        db_roles,
        "CREATE OR REPLACE FUNCTION broker.audit_events_append_only() RETURNS trigger"
        " LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END; $$",
    )
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        # The body contains `%`, so it goes to the driver unparsed, as pg.py does.
        with db_roles.admin_engine.begin() as connection:
            connection.connection.cursor().execute(original)
    assert "Function broker.audit_events_append_only() has been changed." in str(caught.value)
    verify_database(engine)
