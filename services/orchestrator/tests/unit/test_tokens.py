import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import tokens
from app.db.models import ApiTokenRow, AuditRecordRow, PrincipalRow


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        yield session


def test_generated_tokens_are_prefixed_random_and_long():
    first, second = tokens.generate_token(), tokens.generate_token()
    assert first.startswith("glt_") and second.startswith("glt_")
    assert first != second
    assert len(first) >= 4 + 43


def test_hash_is_lowercase_sha256_hex_and_deterministic():
    digest = tokens.hash_token("glt_example")
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == tokens.hash_token("glt_example")
    assert digest != tokens.hash_token("glt_example2")


def test_issued_token_resolves_to_its_principal(session):
    tokens.create_principal(session, "terry", "Terry")
    _, token = tokens.issue_token(session, "terry", "laptop")
    principal = tokens.find_active_principal(session, token)
    assert principal is not None
    assert principal.principal_id == "terry"


def test_only_the_hash_is_stored(session):
    tokens.create_principal(session, "terry", "Terry")
    token_id, token = tokens.issue_token(session, "terry", "laptop")
    row = session.get(ApiTokenRow, token_id)
    assert row.token_hash == tokens.hash_token(token)
    stored = [str(value) for value in vars(row).values()]
    assert all(token not in value for value in stored)


def test_unknown_token_resolves_to_nothing(session):
    tokens.create_principal(session, "terry", "Terry")
    tokens.issue_token(session, "terry", "laptop")
    assert tokens.find_active_principal(session, "glt_not-a-real-token") is None


def test_revoked_token_resolves_to_nothing(session):
    tokens.create_principal(session, "terry", "Terry")
    token_id, token = tokens.issue_token(session, "terry", "laptop")
    tokens.revoke_token(session, token_id)
    assert tokens.find_active_principal(session, token) is None


def test_disabled_principal_resolves_to_nothing(session):
    tokens.create_principal(session, "terry", "Terry")
    _, token = tokens.issue_token(session, "terry", "laptop")
    session.get(PrincipalRow, "terry").disabled_at = datetime.now(UTC)
    assert tokens.find_active_principal(session, token) is None


def test_issue_token_for_missing_principal_raises(session):
    with pytest.raises(tokens.PrincipalNotFoundError):
        tokens.issue_token(session, "ghost", "laptop")


def test_revoke_missing_token_raises(session):
    with pytest.raises(tokens.TokenNotFoundError):
        tokens.revoke_token(session, "tok-missing")


def test_admin_changes_are_audited_once_each(session):
    tokens.create_principal(session, "terry", "Terry")
    token_id, _ = tokens.issue_token(session, "terry", "laptop")
    tokens.revoke_token(session, token_id)
    tokens.revoke_token(session, token_id)
    session.flush()
    rows = session.scalars(select(AuditRecordRow).order_by(AuditRecordRow.action)).all()
    assert [(row.action, row.resource_id) for row in rows] == [
        ("principal.create", "terry"),
        ("token.issue", token_id),
        ("token.revoke", token_id),
    ]
    assert {row.actor for row in rows} == {"admin-cli"}
    assert {row.outcome for row in rows} == {"executed"}


def test_audit_details_never_contain_the_token(session):
    tokens.create_principal(session, "terry", "Terry")
    _, token = tokens.issue_token(session, "terry", "laptop")
    session.flush()
    for row in session.scalars(select(AuditRecordRow)):
        assert token not in str(row.to_contract().model_dump())
