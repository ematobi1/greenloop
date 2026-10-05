"""Startup check: the broker refuses to start on a database its role can't use.

Checks run in groups and stop at the first group with problems, because each needs
the one before it: the schema exists; every relation in it is owned by the connecting
role; the migrations are at head; both append-only triggers on broker.audit_events
exist exactly as migration 2026-10-02_approvals_audit_service_tokens.py created them
(events, timing, level, no WHEN clause, no column list, enabled) and the function
they call still has its original body. Messages name roles, objects and revisions
only, never the URL.

The trigger check detects a disabled, dropped, re-pointed or rewritten trigger at the
next start. It can't stop the broker role, which owns the table, from changing them
while running (ADR 0009, known gaps).

Everything above verify_database is the same in the orchestrator's copy: services
share contracts, not code.
"""

from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.db.tables import SCHEMA

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DOC = "See docs/database-roles.md, section Troubleshooting."

# The pg_class part of scripts/db/transfer-public-ownership.sql: sequences and indexes
# owned by a table follow it, and extension members are left alone.
FOREIGN_OWNED = text(
    """
    SELECT c.relname, c.relowner::regrole::text
    FROM pg_class c
    WHERE c.relnamespace = to_regnamespace(:schema)
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
      AND c.relowner <> CAST(current_user AS regrole)
      AND NOT EXISTS (
          SELECT FROM pg_depend d
          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
            AND d.deptype IN ('a', 'i', 'e')
      )
    ORDER BY c.relname
    """
)


class DatabaseStartupError(RuntimeError):
    pass


def schema_problems(connection: Connection, schema: str) -> list[str]:
    exists = connection.execute(
        text("SELECT to_regnamespace(:schema) IS NOT NULL"), {"schema": schema}
    ).scalar_one()
    return [] if exists else [f"Schema {schema} does not exist."]


def ownership_problems(connection: Connection, schema: str) -> list[str]:
    role = connection.execute(text("SELECT current_user")).scalar_one()
    return [
        f"{schema}.{name} is owned by {owner}, not {role}."
        for name, owner in connection.execute(FOREIGN_OWNED, {"schema": schema})
    ]


def migration_problems(
    connection: Connection, migrations_dir: Path, version_table_schema: str | None
) -> tuple[list[str], str]:
    """Returns the problems and the fix, which depends on which side is behind."""
    scripts = ScriptDirectory(str(migrations_dir))
    heads = set(scripts.get_heads())
    context = MigrationContext.configure(
        connection, opts={"version_table_schema": version_table_schema}
    )
    current = set(context.get_current_heads())
    upgrade = "Run alembic upgrade head for this service, as its own role, then restart."
    if not current:
        return [f"Migrations have not run (head is {', '.join(sorted(heads))})."], upgrade
    if current == heads:
        return [], ""
    known = {revision.revision for revision in scripts.walk_revisions()}
    if unknown := current - known:
        return [
            f"The database is at {', '.join(sorted(unknown))}, which this image doesn't know"
            f" (its head is {', '.join(sorted(heads))})."
        ], r"The image is older than the database: rebuild with .\scripts\dev.ps1 -Service stack."
    return [
        f"Migrations are at {', '.join(sorted(current))}, not head {', '.join(sorted(heads))}."
    ], upgrade


def error_message(service: str, problems: list[str], fix: str) -> str:
    lines = [f"The {service} database is not ready:"]
    lines += [f"  - {problem}" for problem in problems]
    lines += ["Fix:", f"  - {fix}", DOC]
    return "\n".join(lines)


def unreachable_message(service: str, error: DBAPIError) -> str:
    """Names only the driver's error class and SQLSTATE: its text can name host and user."""
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or "none"
    return (
        f"The {service} database could not be checked"
        f" ({type(original).__name__}, SQLSTATE {sqlstate}).\n"
        f"Fix:\n  - Check that the database is up and the role's password in .env is current.\n"
        f"{DOC}"
    )


# tgtype bits (pg_trigger.h): ROW 1, BEFORE 2, INSERT 4, DELETE 8, UPDATE 16, TRUNCATE 32.
APPEND_ONLY_TRIGGERS = {
    "audit_events_no_truncate": 2 | 32,
    "audit_events_no_update_delete": 1 | 2 | 8 | 16,
}
# Whitespace-collapsed body of broker.audit_events_append_only() from the migration.
APPEND_ONLY_BODY = (
    "BEGIN RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP"
    " USING ERRCODE = 'restrict_violation'; END;"
)

# tgenabled: O fires normally, A always; D is disabled and R fires only on replicas.
APPEND_ONLY_TRIGGER_STATE = text(
    """
    SELECT t.tgname, t.tgenabled IN ('O', 'A'), t.tgtype::int,
           t.tgqual IS NULL AND cardinality(CAST(t.tgattr AS int2[])) = 0
    FROM pg_trigger t
    WHERE t.tgrelid = to_regclass('broker.audit_events')
      AND t.tgfoid = to_regprocedure('broker.audit_events_append_only()')
      AND NOT t.tgisinternal
    """
)
APPEND_ONLY_FUNCTION_BODY = text(
    """
    SELECT l.lanname, btrim(regexp_replace(p.prosrc, '\\s+', ' ', 'g'))
    FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang
    WHERE p.oid = to_regprocedure('broker.audit_events_append_only()')
    """
)


def trigger_problems(connection: Connection) -> list[str]:
    function = connection.execute(APPEND_ONLY_FUNCTION_BODY).first()
    if function is None:
        return ["Function broker.audit_events_append_only() is missing."]
    problems = []
    if tuple(function) != ("plpgsql", APPEND_ONLY_BODY):
        problems.append("Function broker.audit_events_append_only() has been changed.")
    found = {
        name: (fires, kind, unconditional)
        for name, fires, kind, unconditional in connection.execute(APPEND_ONLY_TRIGGER_STATE)
    }
    for name, expected_kind in APPEND_ONLY_TRIGGERS.items():
        label = f"Append-only trigger broker.audit_events.{name}"
        if name not in found:
            problems.append(f"{label} is missing.")
            continue
        fires, kind, unconditional = found[name]
        if kind != expected_kind or not unconditional:
            problems.append(f"{label} has been changed (events, timing, WHEN or columns).")
        if not fires:
            problems.append(f"{label} is not enabled.")
    return problems


def verify_database(engine: Engine) -> None:
    """Raises DatabaseStartupError for the first failing group of checks. Postgres only."""
    try:
        with engine.connect() as connection:
            if problems := schema_problems(connection, SCHEMA):
                fix = r"Run .\scripts\db-bootstrap.ps1, then restart."
            elif problems := ownership_problems(connection, SCHEMA):
                fix = (
                    "Find out who created these objects by hand, then give them to"
                    " greenloop_broker or drop them, and restart."
                )
            else:
                problems, fix = migration_problems(connection, MIGRATIONS_DIR, SCHEMA)
                if not problems and (problems := trigger_problems(connection)):
                    fix = (
                        "Save the evidence first, then restore the function and triggers"
                        " from migration 2026-10-02_approvals_audit_service_tokens.py:"
                        " audit_events must stay append-only."
                    )
    except DBAPIError as error:
        raise DatabaseStartupError(unreachable_message("broker", error)) from None
    if problems:
        raise DatabaseStartupError(error_message("broker", problems, fix))
