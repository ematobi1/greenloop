"""Shared Postgres fixtures. Integration tests run only when TEST_DATABASE_URL is set.

TEST_DATABASE_URL must be a superuser on a disposable database. Each session runs
the same role bootstrap and ownership transfer as production (scripts/db), then
migrates as greenloop_orchestrator: downgrade to base and upgrade to head, so never
point TEST_DATABASE_URL at a database whose data matters.
"""

import secrets
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.orm import sessionmaker
from tests.integration.pg import TEST_DATABASE_URL, alembic_command, bootstrap_roles, run_db_script

from app.core import tokens


@dataclass(frozen=True)
class DbRoles:
    admin_engine: Engine
    orchestrator_password: str
    broker_password: str

    def url(self, role: str, password: str | None = None) -> URL:
        if password is None:
            password = (
                self.orchestrator_password
                if role == "greenloop_orchestrator"
                else self.broker_password
            )
        return make_url(TEST_DATABASE_URL).set(username=role, password=password)


@pytest.fixture(scope="session")
def db_roles():
    admin_engine = create_engine(TEST_DATABASE_URL)
    roles = DbRoles(admin_engine, secrets.token_urlsafe(24), secrets.token_urlsafe(24))
    bootstrap_roles(admin_engine, roles.orchestrator_password, roles.broker_password)
    run_db_script(admin_engine, "transfer-public-ownership.sql")
    yield roles
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine(db_roles):
    engine = create_engine(db_roles.url("greenloop_orchestrator"))
    alembic_command(engine, "downgrade", "base")
    alembic_command(engine, "upgrade", "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def new_principal(pg_session_factory):
    def create() -> str:
        principal_id = f"it-{uuid.uuid4().hex[:12]}"
        with pg_session_factory() as session:
            tokens.create_principal(session, principal_id, "Integration")
            session.commit()
        return principal_id

    return create


@pytest.fixture
def principal_id(new_principal) -> str:
    return new_principal()
