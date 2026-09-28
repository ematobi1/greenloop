"""Request middleware: correlation id, Host allowlist, request log, last-resort errors.

Every response carries `X-Request-ID`. The same id is bound to the log context
as `correlation_id` and stored on `request.state`, so audit records and logs for
one request share it. A Host header outside the allowlist is rejected with 400
before any route runs, which blocks DNS-rebinding attempts against a local API.
"""

import time
import uuid
from urllib.parse import urlsplit

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.core.errors import error_response

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def is_allowed_host(host_header: str, allowed_hosts: list[str]) -> bool:
    try:
        parts = urlsplit(f"//{host_header}")
        _ = parts.port
    except ValueError:
        return False
    return parts.hostname is not None and parts.hostname in allowed_hosts


def install_request_middleware(app: FastAPI, allowed_hosts: list[str]) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        if not is_allowed_host(request.headers.get("host", ""), allowed_hosts):
            response: Response = error_response(400, "INVALID_HOST", "Host header not allowed.")
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.error("request_failed", path=request.url.path, exc_info=True)
                response = error_response(500, "INTERNAL_ERROR", "Internal server error.")
        response.headers[REQUEST_ID_HEADER] = correlation_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
