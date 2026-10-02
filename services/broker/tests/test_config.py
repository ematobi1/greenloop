from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import BrokerSettings, env_file_path

SYNTHETIC_URL = "postgresql+psycopg://greenloop_broker:synthetic-pass@127.0.0.1:55432/greenloop"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("BROKER_DATABASE_URL", "APPROVAL_TTL_SECONDS", "GREENLOOP_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_environment_is_empty():
    settings = BrokerSettings(_env_file=None)
    assert settings.database_url is None
    assert settings.approval_ttl == timedelta(minutes=15)


def test_reads_the_environment(monkeypatch):
    monkeypatch.setenv("BROKER_DATABASE_URL", SYNTHETIC_URL)
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "600")
    settings = BrokerSettings(_env_file=None)
    assert settings.database_url.get_secret_value() == SYNTHETIC_URL
    assert settings.approval_ttl == timedelta(minutes=10)


def test_the_database_url_never_appears_in_repr(monkeypatch):
    monkeypatch.setenv("BROKER_DATABASE_URL", SYNTHETIC_URL)
    settings = BrokerSettings(_env_file=None)
    assert "synthetic-pass" not in repr(settings)
    assert "synthetic-pass" not in str(settings.model_dump())


@pytest.mark.parametrize("ttl", ["59", "86401", "0", "soon"])
def test_rejects_a_ttl_outside_one_minute_to_one_day(monkeypatch, ttl):
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", ttl)
    with pytest.raises(ValidationError):
        BrokerSettings(_env_file=None)


def test_empty_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "")
    assert BrokerSettings(_env_file=None).approval_ttl_seconds == 900


def test_loads_the_env_file_and_the_environment_wins(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"BROKER_DATABASE_URL={SYNTHETIC_URL}\nAPPROVAL_TTL_SECONDS=120\n")
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "300")
    settings = BrokerSettings(_env_file=env_file)
    assert settings.database_url.get_secret_value() == SYNTHETIC_URL
    assert settings.approval_ttl_seconds == 300


def test_env_file_is_the_repo_root_env_inside_the_repo():
    path = env_file_path(Path("/repo/services/broker/app/config.py"))
    assert path == Path("/repo/.env").resolve()


def test_no_env_file_outside_the_repo_layout():
    assert env_file_path(Path("/srv/app/config.py")) is None


def test_explicit_env_file_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("GREENLOOP_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(FileNotFoundError):
        env_file_path()
