"""verify_database against real Postgres: each broken state is caught and named, and the
healthy migrated database passes. Every test restores what it changed."""

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from tests.integration.pg import TEST_DATABASE_URL

from app.db.startup_check import MIGRATIONS_DIR, DatabaseStartupError, verify_database

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


def _admin(db_roles, sql: str, **params: str) -> None:
    with db_roles.admin_engine.begin() as connection:
        connection.execute(text(sql), params)


def test_a_migrated_database_owned_by_the_role_passes(engine):
    verify_database(engine)


def test_a_table_owned_by_another_role_is_named(engine, db_roles):
    _admin(db_roles, "CREATE TABLE public.zz_startup_foreign (id int)")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "DROP TABLE public.zz_startup_foreign")
    message = str(caught.value)
    admin_role = db_roles.admin_engine.url.username
    assert (
        f"public.zz_startup_foreign is owned by {admin_role}, not greenloop_orchestrator."
        in message
    )
    assert "db-transfer-ownership.ps1" in message
    assert db_roles.orchestrator_password not in message


def test_alembic_version_owned_by_another_role_is_caught(engine, db_roles):
    admin_role = db_roles.admin_engine.url.username
    _admin(db_roles, f'ALTER TABLE public.alembic_version OWNER TO "{admin_role}"')
    try:
        with pytest.raises(DatabaseStartupError, match=r"public\.alembic_version is owned by"):
            verify_database(engine)
    finally:
        _admin(db_roles, "ALTER TABLE public.alembic_version OWNER TO greenloop_orchestrator")


def test_a_database_behind_head_is_caught(engine, db_roles):
    head = ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    previous = ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(head).down_revision
    _admin(db_roles, "UPDATE public.alembic_version SET version_num = :v", v=previous)
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "UPDATE public.alembic_version SET version_num = :v", v=head)
    assert f"Migrations are at {previous}, not head {head}." in str(caught.value)
    assert "alembic upgrade head" in str(caught.value)


def test_an_unmigrated_database_is_caught(engine, db_roles):
    _admin(db_roles, "ALTER TABLE public.alembic_version RENAME TO zz_alembic_version_hidden")
    try:
        with pytest.raises(DatabaseStartupError, match="Migrations have not run"):
            verify_database(engine)
    finally:
        _admin(db_roles, "ALTER TABLE public.zz_alembic_version_hidden RENAME TO alembic_version")


def test_a_database_ahead_of_the_image_says_rebuild(engine, db_roles):
    head = ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    _admin(db_roles, "UPDATE public.alembic_version SET version_num = 'zz_from_a_newer_image'")
    try:
        with pytest.raises(DatabaseStartupError) as caught:
            verify_database(engine)
    finally:
        _admin(db_roles, "UPDATE public.alembic_version SET version_num = :v", v=head)
    message = str(caught.value)
    assert "zz_from_a_newer_image, which this image doesn't know" in message
    assert "dev.ps1 -Service stack" in message
    assert "alembic upgrade" not in message
