"""Startup check: the broker refuses to start on a database its role can't use.

Every table and sequence in schema broker must be owned by the connecting role, the
migrations must be at head, and both append-only triggers on broker.audit_events
must exist, call the append-only function and be enabled. Messages name roles,
objects and revisions only, never the URL.

The orchestrator has its own copy of the ownership and migration checks: services
share contracts, not code.
"""

from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text

from app.db.tables import SCHEMA

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

APPEND_ONLY_TRIGGERS = ("audit_events_no_truncate", "audit_events_no_update_delete")

# Sequences and indexes owned by a table follow it; extension members are left alone.
FOREIGN_OWNED = text(
    """
    SELECT c.relname, c.relowner::regrole::text
    FROM pg_class c
    WHERE c.relnamespace = CAST(:schema AS regnamespace)
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

# tgenabled: O fires normally, A always; D is disabled and R fires only on replicas.
APPEND_ONLY_TRIGGER_STATE = text(
    """
    SELECT t.tgname, t.tgenabled IN ('O', 'A')
    FROM pg_trigger t
    WHERE t.tgrelid = to_regclass('broker.audit_events')
      AND t.tgfoid = to_regprocedure('broker.audit_events_append_only()')
      AND NOT t.tgisinternal
    """
)


class DatabaseStartupError(RuntimeError):
    pass


def ownership_problems(connection: Connection, schema: str) -> list[str]:
    role = connection.execute(text("SELECT current_user")).scalar_one()
    return [
        f"{schema}.{name} is owned by {owner}, not {role}."
        for name, owner in connection.execute(FOREIGN_OWNED, {"schema": schema})
    ]


def migration_problems(connection: Connection) -> list[str]:
    heads = set(ScriptDirectory(str(MIGRATIONS_DIR)).get_heads())
    context = MigrationContext.configure(connection, opts={"version_table_schema": SCHEMA})
    current = set(context.get_current_heads())
    if not current:
        return [f"Migrations have not run (head is {', '.join(sorted(heads))})."]
    if current != heads:
        return [
            f"Migrations are at {', '.join(sorted(current))}, not head {', '.join(sorted(heads))}."
        ]
    return []


def trigger_problems(connection: Connection) -> list[str]:
    enabled = {name: fires for name, fires in connection.execute(APPEND_ONLY_TRIGGER_STATE)}
    problems = []
    for name in APPEND_ONLY_TRIGGERS:
        if name not in enabled:
            problems.append(f"Append-only trigger broker.audit_events.{name} is missing.")
        elif not enabled[name]:
            problems.append(f"Append-only trigger broker.audit_events.{name} is not enabled.")
    return problems


def error_message(problems: list[str], fix: str) -> str:
    lines = ["The broker database is not ready:"]
    lines += [f"  - {problem}" for problem in problems]
    lines += ["Fix:", f"  - {fix}", "See docs/database-roles.md, section Troubleshooting."]
    return "\n".join(lines)


def verify_database(engine: Engine) -> None:
    """Raises DatabaseStartupError listing the first failing group of checks. Postgres only.

    Each group needs the one before it: an unowned table can't be read, and the
    triggers only exist once the migrations have run.
    """
    with engine.connect() as connection:
        if problems := ownership_problems(connection, SCHEMA):
            fix = "Give every object in schema broker to greenloop_broker, then restart."
        elif problems := migration_problems(connection):
            fix = "Run alembic upgrade head in services/broker as greenloop_broker."
        elif problems := trigger_problems(connection):
            fix = (
                "Re-enable the trigger (ALTER TABLE broker.audit_events ENABLE TRIGGER <name>)"
                " or restore it from migration b0001, and find out who changed it:"
                " audit_events must stay append-only."
            )
    if problems:
        raise DatabaseStartupError(error_message(problems, fix))
