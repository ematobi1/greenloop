"""Per-service database roles (ADR 0009 rules 1 and 10, decisions A and B).

Runs scripts/db/bootstrap-roles.sql and transfer-public-ownership.sql, the files
db-bootstrap.ps1 and db-transfer-ownership.ps1 execute, against the throwaway database.
"""

import secrets

import pytest
from psycopg.errors import RaiseException
from sqlalchemy import create_engine, inspect, literal_column, select, table, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from tests.integration.pg import DB_SCRIPTS, TEST_DATABASE_URL, bootstrap_roles, run_db_script

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

ORCHESTRATOR = "greenloop_orchestrator"
BROKER = "greenloop_broker"


@pytest.fixture
def connect(db_roles):
    engines = []

    def open_as(role: str, password: str | None = None):
        engine = create_engine(db_roles.url(role, password), pool_pre_ping=False)
        engines.append(engine)
        return engine.connect()

    yield open_as
    for engine in engines:
        engine.dispose()


@pytest.fixture
def broker_probe_table(connect):
    with connect(BROKER) as connection:
        connection.execute(text("CREATE TABLE broker.role_probe (id int PRIMARY KEY)"))
        connection.commit()
    yield table("role_probe", schema="broker")
    with connect(BROKER) as connection:
        connection.execute(text("DROP TABLE broker.role_probe"))
        connection.commit()


def test_orchestrator_role_is_denied_on_the_broker_schema(engine, connect, broker_probe_table):
    with connect(ORCHESTRATOR) as connection:
        with pytest.raises(ProgrammingError, match="permission denied for schema broker"):
            connection.execute(select(literal_column("1")).select_from(broker_probe_table))
        connection.rollback()
        with pytest.raises(ProgrammingError, match="permission denied for schema broker"):
            connection.execute(text("CREATE TABLE broker.intruder (id int)"))


def test_broker_role_is_denied_on_every_orchestrator_table(engine, connect):
    names = inspect(engine).get_table_names(schema="public")
    assert {"principals", "api_tokens", "audit_records", "alembic_version"} <= set(names)
    with connect(BROKER) as connection:
        for name in names:
            with pytest.raises(ProgrammingError, match="permission denied for schema public"):
                connection.execute(
                    select(literal_column("1")).select_from(table(name, schema="public"))
                )
            connection.rollback()
        with pytest.raises(ProgrammingError, match="permission denied for schema public"):
            connection.execute(text("CREATE TABLE public.intruder (id int)"))


@pytest.mark.parametrize("role", [ORCHESTRATOR, BROKER])
def test_service_roles_have_no_cluster_privileges(db_roles, role):
    with db_roles.admin_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls,"
                " rolcanlogin FROM pg_roles WHERE rolname = :role"
            ),
            {"role": role},
        ).one()
    assert tuple(row) == (False, False, False, False, False, True)


@pytest.mark.parametrize(("role", "schema"), [(ORCHESTRATOR, "public"), (BROKER, "broker")])
def test_each_role_owns_its_schema_and_searches_it(db_roles, connect, role, schema):
    with db_roles.admin_engine.connect() as connection:
        owner = connection.scalar(
            text("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = :schema"),
            {"schema": schema},
        )
    assert owner == role
    with connect(role) as connection:
        assert connection.scalar(text("SHOW search_path")) == schema


def test_every_object_in_public_is_owned_by_the_orchestrator_after_migrations(engine, db_roles):
    # Extension members (pgvector's functions and types) stay with the superuser.
    with db_roles.admin_engine.connect() as connection:
        others = connection.execute(
            text(
                "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace"
                " AND c.relowner <> 'greenloop_orchestrator'::regrole"
                " AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass"
                " AND d.objid = c.oid AND d.deptype = 'e')"
                " UNION ALL SELECT p.proname FROM pg_proc p"
                " WHERE p.pronamespace = 'public'::regnamespace"
                " AND p.proowner <> 'greenloop_orchestrator'::regrole"
                " AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass"
                " AND d.objid = p.oid AND d.deptype = 'e')"
            )
        ).all()
    assert others == []


def test_bootstrap_clears_the_password_settings(db_roles):
    with db_roles.admin_engine.begin() as connection:
        connection.execute(
            text(
                "SELECT set_config('greenloop.orchestrator_password', :o, false),"
                " set_config('greenloop.broker_password', :b, false)"
            ),
            {"o": db_roles.orchestrator_password, "b": db_roles.broker_password},
        )
        sql = (DB_SCRIPTS / "bootstrap-roles.sql").read_text(encoding="utf-8")
        connection.connection.cursor().execute(sql)
        assert (
            connection.scalar(text("SELECT current_setting('greenloop.orchestrator_password')"))
            == ""
        )
        assert connection.scalar(text("SELECT current_setting('greenloop.broker_password')")) == ""


def test_bootstrap_rotates_passwords(db_roles, connect):
    rotated = secrets.token_urlsafe(24)
    bootstrap_roles(db_roles.admin_engine, rotated, db_roles.broker_password)
    try:
        with connect(ORCHESTRATOR, rotated) as connection:
            assert connection.scalar(text("SELECT current_user")) == ORCHESTRATOR
        with pytest.raises(OperationalError, match="password authentication failed"):
            connect(ORCHESTRATOR, db_roles.orchestrator_password)
    finally:
        bootstrap_roles(
            db_roles.admin_engine, db_roles.orchestrator_password, db_roles.broker_password
        )


@pytest.mark.parametrize("weak", ["", "fifteen-chars!!"])
def test_bootstrap_refuses_a_short_password_and_changes_nothing(db_roles, connect, weak):
    with pytest.raises(RaiseException, match="must be at least 16 characters") as raised:
        bootstrap_roles(db_roles.admin_engine, db_roles.orchestrator_password, weak)
    assert db_roles.orchestrator_password not in str(raised.value)
    with connect(BROKER) as connection:
        assert connection.scalar(text("SELECT current_user")) == BROKER


SENTINELS = """
CREATE TABLE public.zz_sentinel (id serial PRIMARY KEY, label text);
CREATE SEQUENCE public.zz_sentinel_standalone;
CREATE VIEW public.zz_sentinel_view AS SELECT id FROM public.zz_sentinel;
CREATE TYPE public.zz_sentinel_mood AS ENUM ('calm');
CREATE DOMAIN public.zz_sentinel_label AS text;
CREATE TYPE public.zz_sentinel_span AS RANGE (subtype = int4);
CREATE FUNCTION public.zz_sentinel_fn() RETURNS int LANGUAGE sql AS 'SELECT 1';
"""
DROP_SENTINELS = """
DROP VIEW IF EXISTS public.zz_sentinel_view;
DROP TABLE IF EXISTS public.zz_sentinel;
DROP SEQUENCE IF EXISTS public.zz_sentinel_standalone;
DROP TYPE IF EXISTS public.zz_sentinel_mood;
DROP DOMAIN IF EXISTS public.zz_sentinel_label;
DROP TYPE IF EXISTS public.zz_sentinel_span;
DROP FUNCTION IF EXISTS public.zz_sentinel_fn();
"""
SENTINEL_OWNERS = """
SELECT relname AS name, relowner::regrole::text AS owner FROM pg_class
 WHERE relnamespace = 'public'::regnamespace AND relname LIKE 'zz_sentinel%'
UNION ALL
SELECT typname, typowner::regrole::text FROM pg_type
 WHERE typnamespace = 'public'::regnamespace
   AND typname IN (
       'zz_sentinel_mood', 'zz_sentinel_label', 'zz_sentinel_span', 'zz_sentinel_span_multirange'
   )
UNION ALL
SELECT proname, proowner::regrole::text FROM pg_proc
 WHERE pronamespace = 'public'::regnamespace AND proname = 'zz_sentinel_fn'
"""


@pytest.fixture
def superuser_owned_objects(engine, db_roles):
    admin = db_roles.admin_engine
    with admin.begin() as connection:
        connection.connection.cursor().execute(SENTINELS)
    yield admin
    with admin.begin() as connection:
        connection.connection.cursor().execute(DROP_SENTINELS)


def owners(admin) -> dict[str, str]:
    with admin.connect() as connection:
        return dict(connection.execute(text(SENTINEL_OWNERS)).all())


def test_transfer_moves_every_kind_of_object_to_the_orchestrator(superuser_owned_objects):
    admin = superuser_owned_objects
    before = owners(admin)
    assert {
        "zz_sentinel",
        "zz_sentinel_id_seq",
        "zz_sentinel_pkey",
        "zz_sentinel_standalone",
    } <= set(before)
    assert ORCHESTRATOR not in before.values()

    run_db_script(admin, "transfer-public-ownership.sql")

    after = owners(admin)
    assert set(after) == set(before)
    assert set(after.values()) == {ORCHESTRATOR}


def test_transfer_is_idempotent(superuser_owned_objects):
    run_db_script(superuser_owned_objects, "transfer-public-ownership.sql")
    run_db_script(superuser_owned_objects, "transfer-public-ownership.sql")
    assert set(owners(superuser_owned_objects).values()) == {ORCHESTRATOR}


def test_transfer_refuses_to_commit_when_public_is_not_the_orchestrators(superuser_owned_objects):
    admin = superuser_owned_objects
    with admin.begin() as connection:
        connection.execute(text("ALTER SCHEMA public OWNER TO CURRENT_USER"))
    try:
        with pytest.raises(
            RaiseException, match="Schema public is not owned by greenloop_orchestrator"
        ):
            run_db_script(admin, "transfer-public-ownership.sql")
        assert ORCHESTRATOR not in owners(admin).values()
    finally:
        with admin.begin() as connection:
            connection.execute(text("ALTER SCHEMA public OWNER TO greenloop_orchestrator"))


def test_transfer_verification_names_anything_left_behind(superuser_owned_objects):
    script = (DB_SCRIPTS / "transfer-public-ownership.sql").read_text(encoding="utf-8")
    verify_only = script[script.index("DO $verify$") :]
    with (
        pytest.raises(
            RaiseException, match=r"still not owned by greenloop_orchestrator: .*zz_sentinel"
        ),
        superuser_owned_objects.begin() as connection,
    ):
        connection.connection.cursor().execute(verify_only)
