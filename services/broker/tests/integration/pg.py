"""Postgres test helpers for the broker's integration tests."""

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


def bootstrap_roles(admin_engine: Engine, orchestrator_password: str, broker_password: str) -> None:
    """Runs scripts/db/bootstrap-roles.sql, the file db-bootstrap.ps1 executes."""
    sql = (DB_SCRIPTS / "bootstrap-roles.sql").read_text(encoding="utf-8")
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "SELECT set_config('greenloop.orchestrator_password', :o, false),"
                " set_config('greenloop.broker_password', :b, false)"
            ),
            {"o": orchestrator_password, "b": broker_password},
        )
        connection.connection.cursor().execute(sql)
