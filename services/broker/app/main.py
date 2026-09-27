"""Broker HTTP app. Run with `uvicorn app.main:app --port 8100` from services/broker.

Request order for a tool call (phase 3): policy, approval consume if required,
ledger append, MCP forward, ledger append of the result.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.policy import load_policy

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


def create_app(policy_dir: Path = POLICY_DIR) -> FastAPI:
    app = FastAPI(title="GreenLoop Broker", version="0.1.0")
    app.state.policy = load_policy(policy_dir)

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
