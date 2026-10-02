"""Engine for the broker's own database role.

Nothing connects until the engine is used. Connections get a connect timeout, a
statement timeout, and search_path pinned to the broker schema.
"""

from sqlalchemy import Engine, create_engine

from app.config import BrokerSettings

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MS = 10_000


class DatabaseNotConfiguredError(RuntimeError):
    pass


def database_url(settings: BrokerSettings) -> str:
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("BROKER_DATABASE_URL is not set")
    return settings.database_url.get_secret_value()


def make_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c search_path=broker",
        },
    )
