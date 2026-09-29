"""Postgres test helpers shared by the integration conftest and test modules."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SERVICE_ROOT = Path(__file__).resolve().parents[2]


def alembic_command(engine: Engine, name: str, *args: str) -> None:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "app" / "db" / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, name)(config, *args)
