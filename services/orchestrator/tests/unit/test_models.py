from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError

from app.audit import recorder
from app.db.models import AuditRecordRow, PrincipalRow, UtcDateTime


def test_audit_record_round_trips_through_the_table(session_factory, make_audit):
    entry = make_audit("a-1")
    with session_factory() as session:
        session.add(PrincipalRow(principal_id="user-1", display_name="User"))
        recorder.record(session, entry)
        session.commit()
    with session_factory() as session:
        assert session.get(AuditRecordRow, "a-1").to_contract() == entry


def test_non_utc_timestamps_are_normalized_to_utc():
    column = UtcDateTime()
    eastern = datetime(2026, 9, 28, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    stored = column.process_bind_param(eastern, dialect=None)
    assert stored.utcoffset() == timedelta(0)
    assert stored.hour == 12


def test_naive_timestamps_are_rejected(session_factory):
    with session_factory() as session:
        session.add(
            PrincipalRow(
                principal_id="user-1", display_name="User", disabled_at=datetime(2026, 9, 28)
            )
        )
        with pytest.raises(StatementError, match="naive"):
            session.commit()


def test_read_back_timestamps_are_utc_aware(session_factory):
    with session_factory() as session:
        session.add(PrincipalRow(principal_id="user-1", display_name="User"))
        session.commit()
    with session_factory() as session:
        created = session.get(PrincipalRow, "user-1").created_at
        assert created.utcoffset() == timedelta(0)
