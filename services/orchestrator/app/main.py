"""FastAPI application factory. Run with `uvicorn app.main:app` from services/orchestrator."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.registry import build_agent_registry
from app.ai.providers.registry import build_registry
from app.api.v1 import health
from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorEnvelope, register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import install_request_middleware
from app.core.redaction import Redactor
from app.db.session import make_engine, make_session_factory

ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope}
    for status in (400, 401, 403, 404, 409, 422, 500, 501, 502, 503, 504)
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    redactor = Redactor(known_secrets=settings.secret_values())
    configure_logging(settings.log_level, redactor)
    app = FastAPI(title="GreenLoop Orchestrator", version=settings.version)
    app.state.settings = settings
    app.state.redactor = redactor
    app.state.session_factory = (
        make_session_factory(make_engine(settings)) if settings.database_url else None
    )
    app.state.provider_registry = build_registry(settings)
    app.state.agent_registry = build_agent_registry()
    register_error_handlers(app)
    install_request_middleware(app, settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(health.router)
    app.include_router(v1_router, responses=ERROR_RESPONSES)
    return app


app = create_app()
