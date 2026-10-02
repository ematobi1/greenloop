"""Alembic environment for the broker schema. Reads BROKER_DATABASE_URL through
app.config so the URL never lives in a file. The version table lives in broker too,
so the broker role never needs anything in public.

Tests pass an open connection in `config.attributes["connection"]` instead.
"""

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from app.config import BrokerSettings
from app.db.session import database_url
from app.db.tables import SCHEMA, metadata

config = context.config
target_metadata = metadata


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=lambda name, type_, parent: type_ != "schema" or name == SCHEMA,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=database_url(BrokerSettings.from_env()), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_with(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with(connection)
        return
    connectable = engine_from_config(
        {"sqlalchemy.url": database_url(BrokerSettings.from_env())},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_with(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
