"""Broker Postgres fixtures. Integration tests run only when TEST_DATABASE_URL is set.

TEST_DATABASE_URL must be a superuser on a disposable database. Each session runs
the production role bootstrap (scripts/db), then migrates the broker schema as
greenloop_broker: downgrade to base and upgrade to head, so never point
TEST_DATABASE_URL at a database whose data matters.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import URL, Engine, create_engine, make_url
from tests.integration.pg import TEST_DATABASE_URL, alembic_command, bootstrap_roles

from app.approval_store import ApprovalStore
from app.db.session import make_engine


@dataclass(frozen=True)
class DbRoles:
    admin_engine: Engine
    orchestrator_password: str
    broker_password: str

    def url(self, role: str) -> URL:
        password = (
            self.orchestrator_password if role == "greenloop_orchestrator" else self.broker_password
        )
        return make_url(TEST_DATABASE_URL).set(username=role, password=password)


@pytest.fixture(scope="session")
def db_roles():
    admin_engine = create_engine(TEST_DATABASE_URL)
    roles = DbRoles(admin_engine, secrets.token_urlsafe(24), secrets.token_urlsafe(24))
    bootstrap_roles(admin_engine, roles.orchestrator_password, roles.broker_password)
    yield roles
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine(db_roles):
    engine = make_engine(db_roles.url("greenloop_broker").render_as_string(hide_password=False))
    alembic_command(engine, "downgrade", "base")
    alembic_command(engine, "upgrade", "head")
    yield engine
    engine.dispose()


@pytest.fixture
def store(engine) -> ApprovalStore:
    return ApprovalStore(engine, timedelta(minutes=15))
