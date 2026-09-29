"""Shared Postgres fixtures. Integration tests run only when TEST_DATABASE_URL is set.

The engine fixture downgrades to base and upgrades to head once per session, so
never point TEST_DATABASE_URL at a database whose data matters.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.integration.pg import TEST_DATABASE_URL, alembic_command

from app.core import tokens


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
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
