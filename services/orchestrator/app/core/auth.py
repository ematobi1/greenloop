"""Authentication: resolve the principal every request acts for.

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
    row = find_active_principal(session, credentials.credentials)
    principal = (
        None
        if row is None
        else Principal(
            principal_id=row.principal_id,
            display_name=row.display_name,
            role=PrincipalRole(row.role),
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
