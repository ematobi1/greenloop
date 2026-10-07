"""Web sign-in: usernames, argon2id passwords, server-side sessions and lockout (ADR 0012).

- Passwords are hashed with argon2id (argon2-cffi defaults, RFC 9106 low-memory profile)
  and rehashed on sign-in when the parameters change.
- A failed sign-in counts against the username in login_throttle whether or not the
  user exists; MAX_FAILURES in a row lock that username for LOCKOUT. An unknown username
  still runs a full hash verification, so timing and responses never reveal which
  usernames exist.
- A session token is 256 random bits with the `gls_` prefix, shown once to the web
  server; only its SHA256 is stored. Sessions expire after SESSION_LIFETIME and can be
  revoked one at a time or all at once ("sign out everywhere"). Changing a password
  revokes every session.
- Sign-in, sign-out and password changes are audited when the principal is known.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import recorder
from app.db.models import (
    LoginThrottleRow,
    PrincipalRole,
    PrincipalRow,
    UserCredentialRow,
    UserSessionRow,
)
from greenloop_contracts import AuditOutcome, AuditRecord

SESSION_PREFIX = "gls_"
SESSION_LIFETIME = timedelta(hours=12)
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
# A failure count idle this long is forgotten; locks still last LOCKOUT.
STALE_THROTTLE = timedelta(hours=1)
STALE_SESSION = timedelta(days=1)
PRUNE_BATCH = 200
PASSWORD_MIN_CHARS = 12
PASSWORD_MAX_CHARS = 256
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ACTOR = "auth"

_hasher = PasswordHasher()


class InvalidCredentialsError(Exception):
    pass


class LoginThrottledError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("too many failed sign-ins")
        self.retry_after = retry_after


class AccountError(ValueError):
    pass


@dataclass(frozen=True)
class SignedIn:
    principal_id: str
    session_id: str
    token: str
    expires_at: datetime


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    username = normalize_username(username)
    if not USERNAME.match(username):
        raise AccountError("Usernames are 3 to 64 of a-z, 0-9, dot, dash or underscore.")
    return username


def validate_password(password: str) -> str:
    if not PASSWORD_MIN_CHARS <= len(password) <= PASSWORD_MAX_CHARS:
        raise AccountError(
            f"Passwords are {PASSWORD_MIN_CHARS} to {PASSWORD_MAX_CHARS} characters."
        )
    return password


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(32))


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_user(session: Session, principal_id: str, username: str, password: str) -> None:
    username = validate_username(username)
    validate_password(password)
    principal = session.get(PrincipalRow, principal_id)
    if principal is None:
        raise AccountError("No such principal.")
    if principal.role != PrincipalRole.USER.value:
        raise AccountError("Only user principals can sign in to the web app.")
    if session.get(UserCredentialRow, principal_id) is not None:
        raise AccountError("That principal already has a username.")
    try:
        with session.begin_nested():
            session.add(
                UserCredentialRow(
                    principal_id=principal_id,
                    username=username,
                    password_hash=_hasher.hash(password),
                    password_changed_at=datetime.now(UTC),
                )
            )
    except IntegrityError:
        raise AccountError("That username is taken.") from None
    _audit(session, principal_id, "user.create", "user_credential", principal_id, "admin-cli")


def set_password(session: Session, principal_id: str, password: str) -> int:
    """Replace the password and revoke every session. Returns how many were revoked."""
    validate_password(password)
    row = session.get(UserCredentialRow, principal_id)
    if row is None:
        raise AccountError("That principal has no username.")
    row.password_hash = _hasher.hash(password)
    row.password_changed_at = datetime.now(UTC)
    revoked = revoke_all_sessions(session, principal_id, actor="admin-cli")
    _audit(session, principal_id, "user.set_password", "user_credential", principal_id, "admin-cli")
    return revoked


def unlock_user(session: Session, username: str) -> bool:
    """Clear a username's lockout and failure count. Returns whether anything was locked."""
    row = session.get(LoginThrottleRow, normalize_username(username))
    if row is None or (row.failures == 0 and row.locked_until is None):
        return False
    row.failures = 0
    row.locked_until = None
    return True


def prune_stale(session: Session, now: datetime | None = None) -> int:
    """Delete a small batch of throttle rows with no active lock and no change for
    STALE_THROTTLE, and of sessions that expired or were revoked over a day ago. Runs on
    every sign-in attempt, so a flood of new usernames is cleaned up as it arrives. Rows
    another transaction holds are skipped, so concurrent sign-ins never wait on each other.
    """
    now = now or datetime.now(UTC)
    stale = list(
        session.scalars(
            select(LoginThrottleRow.username)
            .where(
                LoginThrottleRow.locked_until.is_(None) | (LoginThrottleRow.locked_until < now),
                LoginThrottleRow.updated_at < now - STALE_THROTTLE,
            )
            .limit(PRUNE_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    removed = 0
    if stale:
        removed += session.execute(
            delete(LoginThrottleRow).where(LoginThrottleRow.username.in_(stale))
        ).rowcount
    old_sessions = list(
        session.scalars(
            select(UserSessionRow.session_id)
            .where(
                (UserSessionRow.expires_at < now - STALE_SESSION)
                | (UserSessionRow.revoked_at < now - STALE_SESSION)
            )
            .limit(PRUNE_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    if old_sessions:
        removed += session.execute(
            delete(UserSessionRow).where(UserSessionRow.session_id.in_(old_sessions))
        ).rowcount
    return removed


def _locked_for(session: Session, username: str, now: datetime) -> int | None:
    """Seconds left on `username`'s lockout, or None. A plain read: no row lock is held
    while the password is checked, so attempts on one username never queue on each other."""
    locked_until = session.scalar(
        select(LoginThrottleRow.locked_until).where(LoginThrottleRow.username == username)
    )
    if locked_until is not None and locked_until > now:
        return int((locked_until - now).total_seconds()) + 1
    return None


def _count_failure(session: Session, username: str, now: datetime) -> None:
    """Add one failure atomically; the MAX_FAILURES-th locks the username."""
    increment = (
        update(LoginThrottleRow)
        .where(LoginThrottleRow.username == username)
        .values(failures=LoginThrottleRow.failures + 1, updated_at=now)
        .returning(LoginThrottleRow.failures)
    )
    failures = session.scalar(increment)
    if failures is None:
        try:
            with session.begin_nested():
                session.add(LoginThrottleRow(username=username, failures=1, updated_at=now))
            failures = 1
        except IntegrityError:
            failures = session.scalar(increment)
    if failures is not None and failures >= MAX_FAILURES:
        session.execute(
            update(LoginThrottleRow)
            .where(
                LoginThrottleRow.username == username,
                LoginThrottleRow.failures >= MAX_FAILURES,
            )
            .values(failures=0, locked_until=now + LOCKOUT, updated_at=now)
        )


def sign_in(session: Session, username: str, password: str, correlation_id: str) -> SignedIn:
    """Raises LoginThrottledError or InvalidCredentialsError; the caller commits either way.

    The lockout is checked before the password and failures are counted after it, so a
    few attempts already in flight when a username locks still get their answer; with at
    most MAX_CONCURRENT_VERIFICATIONS running, that bounds the extra guesses.
    """
    now = datetime.now(UTC)
    username = normalize_username(username)[:64]
    if (wait := _locked_for(session, username, now)) is not None:
        raise LoginThrottledError(wait)

    credential = session.scalars(
        select(UserCredentialRow)
        .join(PrincipalRow, PrincipalRow.principal_id == UserCredentialRow.principal_id)
        .where(
            UserCredentialRow.username == username,
            PrincipalRow.disabled_at.is_(None),
            PrincipalRow.role == PrincipalRole.USER.value,
        )
    ).one_or_none()
    valid = _verify(credential.password_hash if credential else _dummy_hash(), password)
    prune_stale(session, now)
    if credential is None or not valid:
        _count_failure(session, username, now)
        if credential is not None:
            _audit(
                session,
                credential.principal_id,
                "auth.sign_in",
                "user_session",
                "-",
                ACTOR,
                AuditOutcome.DENIED,
                correlation_id,
            )
        raise InvalidCredentialsError

    session.execute(
        update(LoginThrottleRow)
        .where(LoginThrottleRow.username == username)
        .values(failures=0, locked_until=None, updated_at=now)
    )
    if _hasher.check_needs_rehash(credential.password_hash):
        credential.password_hash = _hasher.hash(password)
    token = SESSION_PREFIX + secrets.token_urlsafe(32)
    session_id = f"ses-{uuid.uuid4().hex}"
    expires_at = now + SESSION_LIFETIME
    session.add(
        UserSessionRow(
            session_id=session_id,
            principal_id=credential.principal_id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )
    )
    _audit(
        session,
        credential.principal_id,
        "auth.sign_in",
        "user_session",
        session_id,
        ACTOR,
        AuditOutcome.EXECUTED,
        correlation_id,
    )
    return SignedIn(credential.principal_id, session_id, token, expires_at)


def find_session_principal(session: Session, token: str) -> tuple[PrincipalRow, str] | None:
    """The active principal and session id for a live session token, else None."""
    row = session.execute(
        select(PrincipalRow, UserSessionRow.session_id)
        .join(UserSessionRow, UserSessionRow.principal_id == PrincipalRow.principal_id)
        .where(
            UserSessionRow.token_hash == hash_session_token(token),
            UserSessionRow.revoked_at.is_(None),
            UserSessionRow.expires_at > datetime.now(UTC),
            PrincipalRow.disabled_at.is_(None),
            PrincipalRow.role == PrincipalRole.USER.value,
        )
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


def revoke_session(
    session: Session, principal_id: str, session_id: str, correlation_id: str | None = None
) -> None:
    session.execute(
        update(UserSessionRow)
        .where(
            UserSessionRow.session_id == session_id,
            UserSessionRow.principal_id == principal_id,
            UserSessionRow.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    _audit(
        session,
        principal_id,
        "auth.sign_out",
        "user_session",
        session_id,
        ACTOR,
        AuditOutcome.EXECUTED,
        correlation_id,
    )


def revoke_all_sessions(
    session: Session, principal_id: str, *, actor: str = ACTOR, correlation_id: str | None = None
) -> int:
    revoked = session.execute(
        update(UserSessionRow)
        .where(UserSessionRow.principal_id == principal_id, UserSessionRow.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    ).rowcount
    _audit(
        session,
        principal_id,
        "auth.sign_out_everywhere",
        "user_session",
        "*",
        actor,
        AuditOutcome.EXECUTED,
        correlation_id,
        {"revoked": str(revoked)},
    )
    return revoked


def _audit(
    session: Session,
    principal_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    actor: str,
    outcome: AuditOutcome = AuditOutcome.EXECUTED,
    correlation_id: str | None = None,
    details: dict[str, str] | None = None,
) -> None:
    recorder.record(
        session,
        AuditRecord(
            audit_id=f"aud-{uuid.uuid4().hex}",
            principal_id=principal_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            correlation_id=correlation_id or f"cli-{uuid.uuid4().hex}",
            details=details or {},
        ),
    )
