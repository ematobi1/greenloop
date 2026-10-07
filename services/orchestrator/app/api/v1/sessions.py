"""Web sign-in sessions (ADR 0012).

POST /v1/sessions is the only unauthenticated write route. Wrong usernames and wrong
passwords get the same 401. A locked username, and failed attempts while the endpoint
is being flooded, get 429 with Retry-After; correct credentials for an unlocked
username always work. The session token is returned once, to the web server, which
keeps it in an httpOnly cookie.
"""

import threading
import time
from collections import deque
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.core import accounts
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.db.session import get_session

router = APIRouter(prefix="/sessions", tags=["sessions"])
DbSession = Annotated[Session, Depends(get_session)]

GLOBAL_FAILURE_LIMIT = 30
GLOBAL_WINDOW_SECONDS = 60.0
MAX_CONCURRENT_VERIFICATIONS = 4
VERIFICATION_WAIT_SECONDS = 2.0


class SignInLimiter:
    """Process-wide sign-in guard (ADR 0012).

    - At most MAX_CONCURRENT_VERIFICATIONS argon2 checks run at once, which bounds the
      CPU an unauthenticated flood can use.
    - Failures are counted per window. Past the limit, further failures get 429 instead
      of 401, but every attempt is still verified, so correct credentials always work:
      a flood of bad attempts can't lock everyone out. Per-username lockout is separate.
    """

    def __init__(
        self,
        limit: int = GLOBAL_FAILURE_LIMIT,
        window: float = GLOBAL_WINDOW_SECONDS,
        concurrency: int = MAX_CONCURRENT_VERIFICATIONS,
    ) -> None:
        self._limit = limit
        self._window = window
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()
        self.verifications = threading.BoundedSemaphore(concurrency)

    def record_failure(self) -> int | None:
        """Count a failure. None if under the limit, else seconds until the window clears."""
        now = time.monotonic()
        with self._lock:
            while self._failures and self._failures[0] <= now - self._window:
                self._failures.popleft()
            self._failures.append(now)
            if len(self._failures) > self._limit:
                return int(self._failures[0] + self._window - now) + 1
            return None


def get_limiter(request: Request) -> SignInLimiter:
    return request.app.state.sign_in_limiter


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class SessionOut(BaseModel):
    session_token: str
    principal_id: str
    expires_at: datetime


def _throttled(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "SIGN_IN_THROTTLED",
        "Too many sign-in attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("", status_code=201)
def sign_in(
    body: SignInRequest,
    request: Request,
    session: DbSession,
    limiter: Annotated[SignInLimiter, Depends(get_limiter)],
) -> SessionOut:
    # Never wait long for a slot: a request parked here holds a shared threadpool thread
    # that every other sync endpoint, authentication included, also needs.
    if not limiter.verifications.acquire(timeout=VERIFICATION_WAIT_SECONDS):
        raise _throttled(1)
    try:
        signed_in = accounts.sign_in(
            session, body.username, body.password, request.state.correlation_id
        )
    except accounts.LoginThrottledError as err:
        session.commit()
        raise _throttled(err.retry_after) from None
    except accounts.InvalidCredentialsError:
        session.commit()
        if (wait := limiter.record_failure()) is not None:
            raise _throttled(wait) from None
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong username or password.") from None
    finally:
        limiter.verifications.release()
    session.commit()
    return SessionOut(
        session_token=signed_in.token,
        principal_id=signed_in.principal_id,
        expires_at=signed_in.expires_at,
    )


def _require_session(principal: CurrentPrincipal) -> str:
    if principal.session_id is None:
        raise ApiError(409, "NOT_A_SESSION", "Sign-out applies to web sessions, not API tokens.")
    return principal.session_id


@router.delete("/current", status_code=204)
def sign_out(principal: CurrentPrincipal, request: Request, session: DbSession) -> Response:
    session_id = _require_session(principal)
    accounts.revoke_session(
        session, principal.principal_id, session_id, request.state.correlation_id
    )
    session.commit()
    return Response(status_code=204)


@router.delete("", status_code=204)
def sign_out_everywhere(
    principal: CurrentPrincipal, request: Request, session: DbSession
) -> Response:
    _require_session(principal)
    accounts.revoke_all_sessions(
        session, principal.principal_id, correlation_id=request.state.correlation_id
    )
    session.commit()
    return Response(status_code=204)
