"""Health endpoints. Unauthenticated so load balancers and compose can probe them.

/health is liveness: the process is up. /v1/health is readiness: dependencies
answer. It returns 503 when any check fails and never includes error detail.
"""

from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "unavailable", "not_configured"]


class Readiness(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/health", responses={503: {"model": Readiness}})
def readiness(request: Request, response: Response) -> Readiness:
    checks = {"database": _database_status(request)}
    ready = all(status == "ok" for status in checks.values())
    if not ready:
        response.status_code = 503
    return Readiness(status="ok" if ready else "degraded", checks=checks)


def _database_status(request: Request) -> CheckStatus:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        return "not_configured"
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("readiness_database_unavailable", exc_info=True)
        return "unavailable"
    return "ok"
