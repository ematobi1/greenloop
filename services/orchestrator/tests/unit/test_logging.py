import json
import logging

import structlog
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ANTHROPIC_KEY = "sk-ant-api03-synthetic-test-key-0000000000"
DB_PASSWORD = "synthetic-db-password-123"


def _app_with_secrets():
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        anthropic_api_key=ANTHROPIC_KEY,
        database_url=f"postgresql+psycopg://greenloop:{DB_PASSWORD}@db:5432/greenloop",
    )
    return create_app(settings)


def _lines(captured: str) -> list[dict]:
    return [json.loads(line) for line in captured.splitlines() if line.startswith("{")]


def test_logs_are_json_lines(capsys):
    _app_with_secrets()
    structlog.get_logger("test").info("hello", answer=42)
    events = _lines(capsys.readouterr().err)
    assert {"event": "hello", "answer": 42}.items() <= events[-1].items()
    assert events[-1]["level"] == "info"
    assert events[-1]["timestamp"].endswith("Z")


def test_configured_secrets_never_reach_structlog_output(capsys):
    _app_with_secrets()
    structlog.get_logger("test").warning(
        "leak attempt", key=ANTHROPIC_KEY, nested={"password": DB_PASSWORD}
    )
    output = capsys.readouterr().err
    assert ANTHROPIC_KEY not in output
    assert DB_PASSWORD not in output
    assert "[REDACTED]" in output


def test_configured_secrets_never_reach_stdlib_logging(capsys):
    _app_with_secrets()
    logging.getLogger("third.party").error("connecting with %s", DB_PASSWORD)
    output = capsys.readouterr().err
    assert DB_PASSWORD not in output
    assert "third.party" in output


def test_secrets_in_exception_traces_are_redacted(capsys):
    _app_with_secrets()
    try:
        raise RuntimeError(f"auth failed for token {ANTHROPIC_KEY}")
    except RuntimeError:
        logging.getLogger("worker").exception("job failed")
    output = capsys.readouterr().err
    assert "RuntimeError" in output
    assert ANTHROPIC_KEY not in output


def test_request_log_carries_the_correlation_id(capsys):
    client = TestClient(_app_with_secrets())
    request_id = client.get("/health").headers["X-Request-ID"]
    events = [e for e in _lines(capsys.readouterr().err) if e["event"] == "request_completed"]
    assert events[-1]["correlation_id"] == request_id
    assert events[-1]["status"] == 200
    assert events[-1]["path"] == "/health"


def test_authorization_header_values_never_logged(capsys):
    client = TestClient(_app_with_secrets())
    client.get("/health", headers={"Authorization": "Bearer wrong-secret-value-123"})
    assert "wrong-secret-value-123" not in capsys.readouterr().err
