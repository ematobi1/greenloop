"""API error shape and handlers.

Every error response is `{"error": ErrorDetail}`: code, message and optional
field messages, all safe to show a user. Unhandled exceptions are logged
server-side and returned as a generic 500 with no detail.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from greenloop_contracts import ErrorDetail

logger = structlog.get_logger(__name__)

MAX_MESSAGE_CHARS = 500
HTTP_CODES = {
    400: ("BAD_REQUEST", "Bad request."),
    401: ("UNAUTHENTICATED", "Missing or invalid token."),
    403: ("FORBIDDEN", "Forbidden."),
    404: ("NOT_FOUND", "Not found."),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
}


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.headers = headers


def not_implemented(feature: str, phase: int) -> ApiError:
    return ApiError(
        501, "NOT_IMPLEMENTED", f"{feature} is not implemented yet (roadmap phase {phase})."
    )


def _safe(text: str) -> str:
    return text.strip()[:MAX_MESSAGE_CHARS] or "Error."


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    detail = ErrorDetail(
        code=code,
        message=_safe(message),
        fields={name: _safe(text) for name, text in (fields or {}).items()},
    )
    body = {"error": detail.model_dump(exclude_defaults=True)}
    return JSONResponse(body, status_code=status_code, headers=headers)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(
        exc.status_code, exc.code, exc.message, fields=exc.fields, headers=exc.headers
    )


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", "Request failed."))
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = {}
    for error in exc.errors():
        location = error["loc"][1:] or error["loc"]
        fields[".".join(str(part) for part in location)] = error["msg"]
    return error_response(422, "VALIDATION_FAILED", "Request validation failed.", fields=fields)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "Internal server error.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
