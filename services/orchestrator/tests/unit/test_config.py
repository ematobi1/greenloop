from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, env_file_path, get_settings

ENV_VARS = (
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "BROKER_URL",
    "LOG_LEVEL",
    "ALLOWED_HOSTS",
    "CORS_ORIGINS",
    "GREENLOOP_ENV_FILE",
    "GREENLOOP_CHAT_MODEL",
    "ANTHROPIC_MODEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_environment_is_empty():
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.database_url is None
    assert settings.anthropic_api_key is None
    assert settings.chat_model == "claude-opus-5-5"


def test_greenloop_chat_model_sets_the_chat_model(monkeypatch):
    monkeypatch.setenv("GREENLOOP_CHAT_MODEL", "claude-sonnet-5-5")
    assert Settings(_env_file=None).chat_model == "claude-sonnet-5-5"


def test_anthropic_model_is_no_longer_read(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    assert Settings(_env_file=None).chat_model == "claude-opus-5-5"


@pytest.mark.parametrize("value", ["claude opus", "model;rm", "x" * 129])
def test_rejects_malformed_chat_model(monkeypatch, value):
    monkeypatch.setenv("GREENLOOP_CHAT_MODEL", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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


def test_list_settings_load_from_json_environment_values(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", '["127.0.0.1", "localhost", "orchestrator"]')
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:53000"]')
    settings = Settings(_env_file=None)
    assert settings.allowed_hosts == ["127.0.0.1", "localhost", "orchestrator"]
    assert settings.cors_origins == ["http://localhost:53000"]


@pytest.mark.parametrize("name", ["ALLOWED_HOSTS", "DATABASE_URL", "ANTHROPIC_API_KEY"])
def test_empty_environment_values_fall_back_to_defaults(monkeypatch, name):
    monkeypatch.setenv(name, "")
    settings = Settings(_env_file=None)
    assert settings.allowed_hosts == ["127.0.0.1", "localhost"]
    assert settings.database_url is None
    assert settings.anthropic_api_key is None


def test_secret_values_include_every_secret_and_the_database_password(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-anthropic-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-elevenlabs-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://greenloop:db-pass-123@db/greenloop")
    values = Settings(_env_file=None).secret_values()
    assert "synthetic-anthropic-key" in values
    assert "synthetic-elevenlabs-key" in values
    assert "db-pass-123" in values
    assert "postgresql+psycopg://greenloop:db-pass-123@db/greenloop" in values


def test_secret_values_empty_when_nothing_is_configured():
    assert Settings(_env_file=None).secret_values() == []


SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parents[1]
SYNTHETIC_URL = "postgresql+psycopg://synthetic:synthetic-pass@127.0.0.1:55432/greenloop"


@pytest.fixture
def fake_repo(tmp_path):
    """A repo-shaped tree with a root .env and the package file where config.py lives."""
    package_file = tmp_path / "services" / "orchestrator" / "app" / "core" / "config.py"
    package_file.parent.mkdir(parents=True)
    package_file.touch()
    (tmp_path / ".env").write_text(f"DATABASE_URL={SYNTHETIC_URL}\nLOG_LEVEL=DEBUG\n")
    return tmp_path, package_file


@pytest.fixture
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_env_file_is_the_repo_root_env_from_the_service_folder(monkeypatch):
    monkeypatch.chdir(SERVICE_ROOT)
    assert env_file_path() == REPO_ROOT / ".env"
    assert (REPO_ROOT / "docker-compose.yml").is_file()


def test_root_env_is_found_from_the_service_folder(fake_repo, monkeypatch):
    root, package_file = fake_repo
    monkeypatch.chdir(package_file.parents[2])
    path = env_file_path(package_file)
    assert path == root / ".env"
    settings = Settings(_env_file=path)
    assert settings.database_url.get_secret_value() == SYNTHETIC_URL
    assert settings.log_level == "DEBUG"


def test_real_environment_variables_override_the_env_file(fake_repo, monkeypatch):
    _, package_file = fake_repo
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env:env-pass@db/greenloop")
    settings = Settings(_env_file=env_file_path(package_file))
    assert settings.log_level == "WARNING"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://env:")


def test_greenloop_env_file_overrides_the_default_path(tmp_path, monkeypatch, fresh_settings):
    custom = tmp_path / "ci.env"
    custom.write_text("LOG_LEVEL=ERROR\n")
    monkeypatch.setenv("GREENLOOP_ENV_FILE", str(custom))
    assert env_file_path() == custom
    assert get_settings().log_level == "ERROR"


def test_greenloop_env_file_naming_a_missing_file_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GREENLOOP_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(FileNotFoundError, match="GREENLOOP_ENV_FILE"):
        env_file_path()


def test_blank_greenloop_env_file_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("GREENLOOP_ENV_FILE", "  ")
    assert env_file_path() == REPO_ROOT / ".env"


@pytest.mark.parametrize(
    "package_file",
    ["/srv/app/core/config.py", "/opt/deep/tree/elsewhere/app/core/config.py"],
)
def test_outside_the_repo_layout_no_env_file_is_used(package_file):
    assert env_file_path(package_file) is None


def test_a_missing_root_env_is_harmless(tmp_path):
    package_file = tmp_path / "services" / "orchestrator" / "app" / "core" / "config.py"
    settings = Settings(_env_file=env_file_path(package_file))
    assert settings.database_url is None


def test_output_cap_leaves_room_for_thinking_and_for_the_prompt():
    """Opus 5.5 thinking counts against max_tokens: at effort medium a hard prompt used
    all of 16k and was cut off mid-reply (paid smoke run, 2026-10-01). 32k doubles that
    while the 150k context limit still leaves 118k for system prompt, history and memory."""
    settings = Settings(_env_file=None)
    assert settings.ai_max_output_tokens == 32000
    assert settings.ai_context_token_limit == 150000
    assert settings.ai_context_token_limit - settings.ai_max_output_tokens >= 100000
