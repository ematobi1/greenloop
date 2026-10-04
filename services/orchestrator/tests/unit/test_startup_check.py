"""The startup check runs only for Postgres, and a failing check stops the app starting."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main
from app.core.config import Settings
from app.db.startup_check import DatabaseStartupError, error_message


def _settings(database_url: str | None) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        database_url=SecretStr(database_url) if database_url else None,
    )


@pytest.fixture
def calls(monkeypatch) -> list[str]:
    recorded: list[str] = []
    monkeypatch.setattr(
        main, "verify_database", lambda engine: recorded.append(engine.url.drivername)
    )
    return recorded


def test_postgres_runs_the_check_at_startup(calls):
    with TestClient(main.create_app(_settings("postgresql+psycopg://u:p@localhost:1/db"))):
        pass
    assert calls == ["postgresql+psycopg"]


@pytest.mark.parametrize("database_url", [None, "sqlite://"])
def test_other_databases_skip_the_check(calls, database_url):
    with TestClient(main.create_app(_settings(database_url))):
        pass
    assert calls == []


def test_a_failing_check_stops_startup(monkeypatch):
    def fail(engine):
        raise DatabaseStartupError("not ready")

    monkeypatch.setattr(main, "verify_database", fail)
    app = main.create_app(_settings("postgresql+psycopg://u:p@localhost:1/db"))
    with pytest.raises(DatabaseStartupError, match="not ready"), TestClient(app):
        pass


def test_error_message_lists_problems_fixes_and_the_doc():
    message = error_message("orchestrator", ["a is wrong.", "b is wrong."], ["Do c."])
    assert message.splitlines() == [
        "The orchestrator database is not ready:",
        "  - a is wrong.",
        "  - b is wrong.",
        "Fix:",
        "  - Do c.",
        "See docs/database-roles.md, section Troubleshooting.",
    ]
