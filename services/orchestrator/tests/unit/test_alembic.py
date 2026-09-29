from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import Settings
from app.db.session import DatabaseNotConfiguredError, database_url

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_has_a_single_linear_head():
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "app" / "db" / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["0002"]


def test_database_url_requires_configuration():
    with pytest.raises(DatabaseNotConfiguredError):
        database_url(Settings(_env_file=None, database_url=None))


def test_database_url_unwraps_secret():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@db/greenloop")
    assert database_url(settings) == "postgresql+psycopg://u:p@db/greenloop"
