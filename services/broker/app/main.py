"""Broker HTTP app. Run with `uvicorn app.main:app --port 8100` from services/broker.

Only reachable on the internal network: compose does not publish its port (ADR 0009).

Request order for a tool call (phase 3): policy, approval consume if required,
ledger append, MCP forward, ledger append of the result.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError

from app.api import ApiError, error_response, router
from app.approval_store import ApprovalStore
from app.config import BrokerSettings, get_settings
from app.db.session import make_engine
from app.policy import load_policy

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """422 with the failing field paths and messages; never the submitted values."""
    fields = {
        ".".join(str(part) for part in item["loc"][1:]) or "body": item["msg"]
        for item in error.errors()
    }
    return JSONResponse(
        {
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "The request is not valid.",
                "fields": fields,
            }
        },
        status_code=422,
    )


def create_app(
    settings: BrokerSettings | None = None,
    policy_dir: Path = POLICY_DIR,
    engine: Engine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if engine is None and settings.database_url is not None:
        try:
            engine = make_engine(settings.database_url.get_secret_value())
        except ArgumentError:
            # The original message can quote the URL, password included.
            raise RuntimeError("BROKER_DATABASE_URL is not a valid database URL.") from None

    app = FastAPI(title="GreenLoop Broker", version="0.1.0")
    app.state.policy = load_policy(policy_dir)
    app.state.engine = engine
    app.state.approval_store = (
        None if engine is None else ApprovalStore(engine, settings.approval_ttl)
    )
    app.add_exception_handler(ApiError, lambda request, error: error_response(error))
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tool-calls")
    async def create_tool_call() -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "NOT_IMPLEMENTED",
                    "message": "Tool calls are not implemented yet (roadmap phase 3).",
                }
            },
            status_code=501,
        )

    return app


app = create_app()
