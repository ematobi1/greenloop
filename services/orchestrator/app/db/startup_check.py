"""Startup check: the orchestrator refuses to start on a database its role can't use.

Every table, view and sequence in public must be owned by the connecting role, and
the migrations must be at head. Messages name roles, objects and revisions only,
never the URL.
"""

from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
SCHEMA = "public"

# Same scope as scripts/db/transfer-public-ownership.sql: sequences and indexes owned
# by a table follow it, and extension members are left alone.
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


class DatabaseStartupError(RuntimeError):
    pass


def ownership_problems(connection: Connection, schema: str) -> list[str]:
    role = connection.execute(text("SELECT current_user")).scalar_one()
    return [
        f"{schema}.{name} is owned by {owner}, not {role}."
        for name, owner in connection.execute(FOREIGN_OWNED, {"schema": schema})
    ]


def migration_problems(
    connection: Connection, migrations_dir: Path, version_table_schema: str | None = None
) -> list[str]:
    heads = set(ScriptDirectory(str(migrations_dir)).get_heads())
    context = MigrationContext.configure(
        connection, opts={"version_table_schema": version_table_schema}
    )
    current = set(context.get_current_heads())
    if not current:
        return [f"Migrations have not run (head is {', '.join(sorted(heads))})."]
    if current != heads:
        return [
            f"Migrations are at {', '.join(sorted(current))}, not head {', '.join(sorted(heads))}."
        ]
    return []


def error_message(service: str, problems: list[str], fixes: list[str]) -> str:
    lines = [f"The {service} database is not ready:"]
    lines += [f"  - {problem}" for problem in problems]
    lines += ["Fix:"] + [f"  - {fix}" for fix in fixes]
    lines.append("See docs/database-roles.md, section Troubleshooting.")
    return "\n".join(lines)


def verify_database(engine: Engine) -> None:
    """Raises DatabaseStartupError listing every problem found. Postgres only."""
    with engine.connect() as connection:
        problems = ownership_problems(connection, SCHEMA)
        fixes: list[str] = []
        if problems:
            # The role usually can't read a table it doesn't own, alembic_version included.
            fixes.append(r"Run .\scripts\db-transfer-ownership.ps1, then restart.")
        else:
            problems = migration_problems(connection, MIGRATIONS_DIR)
            if problems:
                fixes.append(
                    "Run alembic upgrade head in services/orchestrator as greenloop_orchestrator."
                )
    if problems:
        raise DatabaseStartupError(error_message("orchestrator", problems, fixes))
