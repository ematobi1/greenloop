"""Postgres test helpers shared by the integration conftest and test modules."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SERVICE_ROOT = Path(__file__).resolve().parents[2]
DB_SCRIPTS = SERVICE_ROOT.parents[1] / "scripts" / "db"


def alembic_command(engine: Engine, name: str, *args: str) -> None:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "app" / "db" / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, name)(config, *args)


def run_db_script(admin_engine: Engine, name: str, settings: dict[str, str] | None = None) -> None:
    """Runs a scripts/db/*.sql file in one transaction, as the production scripts do.

    The SQL goes to the driver unparsed (it contains format() `%s`), and settings are
    applied first through bound parameters, the same way psql's :'variable' quoting does.
    """
    sql = (DB_SCRIPTS / name).read_text(encoding="utf-8")
    with admin_engine.begin() as connection:
        for key, value in (settings or {}).items():
            connection.execute(
                text("SELECT set_config(:key, :value, false)"), {"key": key, "value": value}
            )
        connection.connection.cursor().execute(sql)


def bootstrap_roles(admin_engine: Engine, orchestrator_password: str, broker_password: str) -> None:
    run_db_script(
        admin_engine,
        "bootstrap-roles.sql",
        {
            "greenloop.orchestrator_password": orchestrator_password,
            "greenloop.broker_password": broker_password,
        },
    )
