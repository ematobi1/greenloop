"""SQLAlchemy engine, session factory and the request-scoped session dependency.

Nothing connects until a session is used. Postgres connections get a connect
timeout and a statement timeout so a stuck database cannot hang a request.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import ApiError

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MS = 10_000


class DatabaseNotConfiguredError(RuntimeError):
    pass


def database_url(settings: Settings) -> str:
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return settings.database_url.get_secret_value()


def make_engine(settings: Settings) -> Engine:
    url = database_url(settings)
    connect_args = {}
    if make_url(url).get_backend_name() == "postgresql":
        connect_args = {
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        }
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] | None = request.app.state.session_factory
    if session_factory is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not configured.")
    with session_factory() as session:
        yield session
