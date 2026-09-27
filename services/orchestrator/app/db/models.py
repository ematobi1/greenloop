"""ORM models. Alembic autogenerates migrations from `Base.metadata`.

TODO(phase-2): memory_records (append-only, pgvector embedding, principal and scope
indexes), principals. TODO(phase-3): approvals, audit_records. TODO(phase-4): jobs.
Every table gets created_at and updated_at.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
