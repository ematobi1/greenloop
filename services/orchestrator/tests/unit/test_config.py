import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_VARS = ("DATABASE_URL", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "BROKER_URL", "LOG_LEVEL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_environment_is_empty():
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.database_url is None
    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-opus-5-5"


def test_loads_values_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/greenloop")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("BROKER_URL", "http://broker:8100")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "synthetic-test-key"
    assert settings.broker_url == "http://broker:8100"
    assert settings.log_level == "DEBUG"


def test_secrets_do_not_appear_in_repr(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@db/greenloop")
    rendered = repr(Settings(_env_file=None))
    assert "synthetic-test-key" not in rendered
    assert "hunter2" not in rendered


def test_rejects_invalid_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
