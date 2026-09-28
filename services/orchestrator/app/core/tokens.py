"""Principals and their bearer tokens.

A token is 256 random bits shown once at issue time. Only its SHA256 is stored,
so a database leak does not leak usable tokens. Issuing and revoking a token are
audited in the same transaction as the change.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import recorder
from app.db.models import ApiTokenRow, PrincipalRow
from greenloop_contracts import AuditOutcome, AuditRecord

TOKEN_PREFIX = "glt_"  # noqa: S105 - public marker, not a secret
ADMIN_ACTOR = "admin-cli"


class PrincipalNotFoundError(LookupError):
    pass


class TokenNotFoundError(LookupError):
    pass


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_active_principal(session: Session, token: str) -> PrincipalRow | None:
    return session.scalars(
        select(PrincipalRow)
        .join(ApiTokenRow, ApiTokenRow.principal_id == PrincipalRow.principal_id)
        .where(
            ApiTokenRow.token_hash == hash_token(token),
            ApiTokenRow.revoked_at.is_(None),
            PrincipalRow.disabled_at.is_(None),
        )
    ).one_or_none()


def create_principal(session: Session, principal_id: str, display_name: str) -> PrincipalRow:
    principal = PrincipalRow(principal_id=principal_id, display_name=display_name)
    session.add(principal)
    session.flush()
    _audit(session, principal_id, "principal.create", "principal", principal_id)
    return principal


def issue_token(session: Session, principal_id: str, label: str) -> tuple[str, str]:
    """Return (token_id, token). The caller shows the token once and never stores it."""
    if session.get(PrincipalRow, principal_id) is None:
        raise PrincipalNotFoundError(principal_id)
    token = generate_token()
    token_id = f"tok-{uuid.uuid4().hex}"
    session.add(
        ApiTokenRow(
            token_id=token_id, principal_id=principal_id, token_hash=hash_token(token), label=label
        )
    )
    session.flush()
    _audit(session, principal_id, "token.issue", "api_token", token_id, {"label": label})
    return token_id, token


def revoke_token(session: Session, token_id: str) -> None:
    row = session.get(ApiTokenRow, token_id)
    if row is None:
        raise TokenNotFoundError(token_id)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        _audit(session, row.principal_id, "token.revoke", "api_token", token_id)


def _audit(
    session: Session,
    principal_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, str] | None = None,
) -> None:
    recorder.record(
        session,
        AuditRecord(
            audit_id=f"aud-{uuid.uuid4().hex}",
            principal_id=principal_id,
            actor=ADMIN_ACTOR,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=AuditOutcome.EXECUTED,
            correlation_id=f"cli-{uuid.uuid4().hex}",
            details=details or {},
        ),
    )
