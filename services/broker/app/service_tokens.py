"""Service tokens: how the orchestrator authenticates to the broker (ADR 0009 rule 2,
decision C).

A token is 32 random bytes (URL-safe base64) with a `glsvc_` prefix. Only its SHA256
is stored; the token itself is returned once by `issue` and never logged. A
high-entropy token needs no slow hash: SHA256 lookup is enough, and the stored hash
is then compared with hmac.compare_digest. Rotation: issue a new token, switch the
orchestrator to it, then revoke the old one; several active tokens may coexist.
Issue and revoke are audited; refused authentications are audited by the caller.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, func, insert, select, update

from app import audit
from app.db.tables import service_tokens
from greenloop_contracts import AuditOutcome

SERVICE_KEY_PREFIX = "glsvc_"
CLI_ACTOR = "broker-cli"
CLI_PRINCIPAL = "broker-admin"


@dataclass(frozen=True)
class ServiceTokenInfo:
    token_id: str
    name: str
    created_at: datetime
    revoked_at: datetime | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(engine: Engine, name: str) -> tuple[str, str]:
    """A new token for `name`. Returns (token_id, token); the token is not stored."""
    token = SERVICE_KEY_PREFIX + secrets.token_urlsafe(32)
    token_id = f"svc-{uuid.uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(
            insert(service_tokens).values(
                token_id=token_id, name=name, token_hash=hash_token(token)
            )
        )
        audit.record(
            connection,
            principal_id=CLI_PRINCIPAL,
            actor=CLI_ACTOR,
            action="service_token.issue",
            outcome=AuditOutcome.ALLOWED,
            correlation_id=token_id,
            resource_type="service_token",
            resource_id=token_id,
            details={"name": name},
        )
    return token_id, token


def revoke(engine: Engine, token_id: str) -> bool:
    """Revokes an active token. False if it does not exist or is already revoked."""
    with engine.begin() as connection:
        revoked = connection.execute(
            update(service_tokens)
            .where(service_tokens.c.token_id == token_id, service_tokens.c.revoked_at.is_(None))
            .values(revoked_at=func.now(), updated_at=func.now())
            .returning(service_tokens.c.name)
        ).first()
        if revoked is None:
            return False
        audit.record(
            connection,
            principal_id=CLI_PRINCIPAL,
            actor=CLI_ACTOR,
            action="service_token.revoke",
            outcome=AuditOutcome.ALLOWED,
            correlation_id=token_id,
            resource_type="service_token",
            resource_id=token_id,
            details={"name": revoked.name},
        )
    return True


def list_all(engine: Engine) -> list[ServiceTokenInfo]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                service_tokens.c.token_id,
                service_tokens.c.name,
                service_tokens.c.created_at,
                service_tokens.c.revoked_at,
            ).order_by(service_tokens.c.created_at, service_tokens.c.token_id)
        )
        return [ServiceTokenInfo(*row) for row in rows]


def authenticate(engine: Engine, presented: str) -> ServiceTokenInfo | None:
    """The active token matching `presented`, or None. Never raises on bad input."""
    if not presented.startswith(SERVICE_KEY_PREFIX):
        return None
    digest = hash_token(presented)
    with engine.connect() as connection:
        row = connection.execute(
            select(
                service_tokens.c.token_id,
                service_tokens.c.name,
                service_tokens.c.created_at,
                service_tokens.c.revoked_at,
                service_tokens.c.token_hash,
            ).where(service_tokens.c.token_hash == digest, service_tokens.c.revoked_at.is_(None))
        ).first()
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        return None
    return ServiceTokenInfo(row.token_id, row.name, row.created_at, row.revoked_at)
