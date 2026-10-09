"""Health endpoints. Unauthenticated so load balancers and compose can probe them.

/health is liveness: the process is up. /v1/health is readiness: dependencies
answer. It returns 503 when any check fails and never includes error detail.
"""

import asyncio
import time
from typing import Literal

import httpx2
import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

BROKER_TIMEOUT_SECONDS = 2.0
BROKER_CACHE_SECONDS = 5.0

CheckStatus = Literal["ok", "unavailable", "not_configured"]


class Readiness(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/health", responses={503: {"model": Readiness}})
async def readiness(request: Request, response: Response) -> Readiness:
    checks = {
        "database": await asyncio.to_thread(_database_status, request),
        "broker": await _cached_broker_status(request),
    }
    # A broker that isn't configured (local runs) doesn't make the orchestrator unready;
    # one that is configured and down does.
    ready = checks["database"] == "ok" and checks["broker"] in ("ok", "not_configured")
    if not ready:
        response.status_code = 503
    return Readiness(status="ok" if ready else "degraded", checks=checks)


async def broker_status(
    broker_url: str | None, transport: httpx2.AsyncBaseTransport | None = None
) -> CheckStatus:
    """The broker's liveness, status only, within BROKER_TIMEOUT_SECONDS."""
    if not broker_url:
        return "not_configured"
    try:
        async with (
            asyncio.timeout(BROKER_TIMEOUT_SECONDS),
            httpx2.AsyncClient(
                timeout=BROKER_TIMEOUT_SECONDS, transport=transport, trust_env=False
            ) as client,
        ):
            reply = await client.get(f"{broker_url.rstrip('/')}/health")
    except (httpx2.HTTPError, TimeoutError):
        logger.warning("readiness_broker_unavailable")
        return "unavailable"
    return "ok" if reply.status_code == 200 else "unavailable"


class _BrokerCache:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.status: CheckStatus | None = None
        self.checked_at = 0.0


async def _cached_broker_status(request: Request) -> CheckStatus:
    """broker_status, reused for BROKER_CACHE_SECONDS per app.

    /v1/health is unauthenticated, so callers must not be able to multiply outbound
    broker calls: concurrent probes wait on one lock and share the answer.
    """
    state = request.app.state
    cache: _BrokerCache | None = getattr(state, "broker_cache", None)
    if cache is None:
        cache = state.broker_cache = _BrokerCache()
    async with cache.lock:
        now = time.monotonic()
        if cache.status is None or now - cache.checked_at >= BROKER_CACHE_SECONDS:
            cache.status = await broker_status(state.settings.broker_url)
            cache.checked_at = time.monotonic()
        return cache.status


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
