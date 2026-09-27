"""SQLAlchemy engine and session factory. Nothing connects until a session is used."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


def database_url(settings: Settings) -> str:
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return settings.database_url.get_secret_value()


def make_engine(settings: Settings) -> Engine:
    return create_engine(database_url(settings), pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
