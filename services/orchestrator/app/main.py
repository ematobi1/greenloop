"""FastAPI application factory. Run with `uvicorn app.main:app` from services/orchestrator."""

from fastapi import FastAPI

from app.api.v1 import health
from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="GreenLoop Orchestrator", version="0.1.0")
    app.state.settings = settings
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1_router)
    return app


app = create_app()
