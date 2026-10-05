"""Startup check: the orchestrator refuses to start on a database its role can't use.

Checks run in groups and stop at the first group with problems, because each needs
the one before it: every relation in public (tables, views, materialized views,
foreign tables, sequences) is owned by the connecting role, then the migrations are
at head. Functions and types are not checked. Messages name roles, objects and
revisions only, never the URL.

Everything above verify_database is the same in the broker's copy: services share
contracts, not code.
"""

from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

SCHEMA = "public"

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


def verify_database(engine: Engine) -> None:
    """Raises DatabaseStartupError for the first failing group of checks. Postgres only."""
    try:
        with engine.connect() as connection:
            if problems := schema_problems(connection, SCHEMA):
                fix = r"Run .\scripts\db-bootstrap.ps1, then restart."
            elif problems := ownership_problems(connection, SCHEMA):
                # The role usually can't read a table it doesn't own, alembic_version included.
                fix = r"Run .\scripts\db-transfer-ownership.ps1, then restart."
            else:
                problems, fix = migration_problems(connection, MIGRATIONS_DIR, None)
    except DBAPIError as error:
        raise DatabaseStartupError(unreachable_message("orchestrator", error)) from None
    if problems:
        raise DatabaseStartupError(error_message("orchestrator", problems, fix))
