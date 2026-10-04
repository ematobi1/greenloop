"""The startup check runs only for Postgres, and a failing check stops the app starting."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import main
from app.config import BrokerSettings
from app.db.startup_check import DatabaseStartupError, error_message


@pytest.fixture
def calls(monkeypatch) -> list[str]:
    recorded: list[str] = []
    monkeypatch.setattr(
        main, "verify_database", lambda engine: recorded.append(engine.url.drivername)
    )
    return recorded


def test_postgres_runs_the_check_at_startup(calls):
    engine = create_engine("postgresql+psycopg://u:p@localhost:1/db")
    with TestClient(main.create_app(BrokerSettings(_env_file=None), engine=engine)):
        pass
    assert calls == ["postgresql+psycopg"]


def test_no_database_skips_the_check(calls):
    with TestClient(main.create_app(BrokerSettings(_env_file=None))):
        pass
    assert calls == []


def test_other_databases_skip_the_check(calls):
    with TestClient(
        main.create_app(BrokerSettings(_env_file=None), engine=create_engine("sqlite://"))
    ):
        pass
    assert calls == []


def test_a_failing_check_stops_startup(monkeypatch):
    def fail(engine):
        raise DatabaseStartupError("not ready")

    monkeypatch.setattr(main, "verify_database", fail)
    engine = create_engine("postgresql+psycopg://u:p@localhost:1/db")
    app = main.create_app(BrokerSettings(_env_file=None), engine=engine)
    with pytest.raises(DatabaseStartupError, match="not ready"), TestClient(app):
        pass


def test_error_message_lists_problems_the_fix_and_the_doc():
    assert error_message(["a is wrong.", "b is wrong."], "Do c.").splitlines() == [
        "The broker database is not ready:",
        "  - a is wrong.",
        "  - b is wrong.",
        "Fix:",
        "  - Do c.",
        "See docs/database-roles.md, section Troubleshooting.",
    ]
