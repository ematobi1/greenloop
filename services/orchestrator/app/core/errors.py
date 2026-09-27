"""API error shape and handlers.

Every error response is `{"error": {"code", "message", "fields"?}}`. Unhandled
exceptions are logged server-side and returned as a generic 500 with no detail.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_implemented(feature: str, phase: int) -> ApiError:
    return ApiError(
        501, "NOT_IMPLEMENTED", f"{feature} is not implemented yet (roadmap phase {phase})."
    )


def _body(code: str, message: str, fields: dict[str, str] | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return {"error": error}


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = {".".join(str(p) for p in err["loc"]): err["msg"] for err in exc.errors()}
    return JSONResponse(
        _body("VALIDATION_FAILED", "Request validation failed.", fields), status_code=422
    )


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", exc_info=exc)
    return JSONResponse(_body("INTERNAL_ERROR", "Internal server error."), status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
