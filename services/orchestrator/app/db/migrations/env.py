"""Alembic environment. Reads DATABASE_URL through app settings so the URL never lives in a file.

Tests pass an open connection in `config.attributes["connection"]` instead.
"""

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from app.core.config import get_settings
from app.db.models import Base
from app.db.session import database_url

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(get_settings()), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with(connection)
        return
    connectable = engine_from_config(
        {"sqlalchemy.url": database_url(get_settings())},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_with(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
