"""Authentication: resolve the principal every request acts for.

Two bearer credentials are accepted: API tokens (`glt_`, for the CLI and services) and
web sessions (`gls_`, from sign-in; see accounts.py and ADR 0012). Session-backed
requests carry their session id so sign-out can revoke exactly that session.

Memory and permissions are scoped to the principal server-side, so every
endpoint beyond the health checks depends on `get_current_principal`. A missing,
unknown or revoked token, or a disabled principal, all return the same 401. The
lookup's transaction is ended before returning, so the request session holds no
connection until the endpoint uses it again.
"""

from dataclasses import dataclass
from typing import Annotated

import structlog
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.accounts import SESSION_PREFIX, find_session_principal
from app.core.errors import ApiError
from app.core.tokens import find_active_principal
from app.db.models import PrincipalRole
from app.db.session import get_session

logger = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    role: PrincipalRole = PrincipalRole.USER
    session_id: str | None = None

    @property
    def is_system(self) -> bool:
        return self.role is PrincipalRole.SYSTEM


def _unauthenticated() -> ApiError:
    return ApiError(
        401,
        "UNAUTHENTICATED",
        "Missing or invalid token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    if credentials is None:
        raise _unauthenticated()
    token = credentials.credentials
    session_id = None
    if token.startswith(SESSION_PREFIX):
        found = find_session_principal(session, token)
        row, session_id = found if found is not None else (None, None)
    else:
        row = find_active_principal(session, token)
    principal = (
        None
        if row is None
        else Principal(
            principal_id=row.principal_id,
            display_name=row.display_name,
            role=PrincipalRole(row.role),
            session_id=session_id,
        )
    )
    # After building Principal: rollback expires `row`. Ending the read here keeps a long
    # chat stream from holding a connection idle in transaction.
    session.rollback()
    if principal is None:
        logger.warning("authentication_failed")
        raise _unauthenticated()
    structlog.contextvars.bind_contextvars(principal_id=principal.principal_id)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
