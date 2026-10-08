import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ApiError, ErrorEnvelope, not_implemented
from app.main import create_app


def _v1_routes() -> list[tuple[str, str]]:
    app = create_app(Settings(_env_file=None, environment="test"))
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "x-1", path))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/v1/")
        for method in sorted(operations)
    ]


BUILT_ROUTES = {
    ("GET", "/v1/health"),
    ("POST", "/v1/sessions"),
    ("DELETE", "/v1/sessions"),
    ("DELETE", "/v1/sessions/current"),
    ("GET", "/v1/sessions/current"),
    ("GET", "/v1/audit-records"),
    ("GET", "/v1/memory-records"),
    ("POST", "/v1/memory-records"),
    ("GET", "/v1/memory-records/x-1"),
    ("DELETE", "/v1/memory-records/x-1"),
    ("GET", "/v1/memory-records/x-1/history"),
    ("POST", "/v1/memory-records/x-1/revisions"),
    ("GET", "/v1/conversations"),
    ("POST", "/v1/conversations"),
    ("GET", "/v1/conversations/x-1"),
    ("DELETE", "/v1/conversations/x-1"),
    ("GET", "/v1/conversations/x-1/messages"),
    ("POST", "/v1/conversations/x-1/messages"),
    ("POST", "/v1/conversations/x-1/messages/x-1/remember"),
    ("POST", "/v1/plans"),
    ("GET", "/v1/plans"),
    ("GET", "/v1/plans/x-1"),
    ("DELETE", "/v1/plans/x-1"),
    ("GET", "/v1/agents"),
    ("GET", "/v1/agents/x-1"),
    ("POST", "/v1/dispatches"),
    ("GET", "/v1/approvals"),
    ("GET", "/v1/approvals/x-1"),
    ("POST", "/v1/approvals/x-1/decisions"),
}
V1_ROUTES = _v1_routes()
UNBUILT_ROUTES = [route for route in V1_ROUTES if route not in BUILT_ROUTES]


def test_every_v1_route_is_covered():
    assert len(V1_ROUTES) == 29
    assert set(V1_ROUTES) >= BUILT_ROUTES


@pytest.mark.parametrize(("method", "path"), UNBUILT_ROUTES)
def test_unbuilt_routes_return_501_error_shape(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 501
    error = response.json()["error"]
    assert error["code"] == "NOT_IMPLEMENTED"
    assert re.search(r"roadmap phase \d", error["message"])


def test_unknown_path_returns_404_error_shape(client):
    response = client.get("/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unhandled_error_hides_internal_detail(settings):
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Internal server error."}
    }
    assert "secret internal detail" not in response.text


def test_api_error_bodies_are_contract_error_details(settings):
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal")

    @app.get("/later")
    async def later() -> None:
        raise not_implemented("Something later", phase=5)

    client = TestClient(app, raise_server_exceptions=False)
    for path, status in (("/later", 501), ("/v1/nope", 404), ("/boom", 500)):
        response = client.get(path)
        assert response.status_code == status
        ErrorEnvelope.model_validate(response.json())


def test_method_not_allowed_has_its_own_code(client):
    response = client.put("/health")
    assert response.status_code == 405
    assert response.json()["error"] == {
        "code": "METHOD_NOT_ALLOWED",
        "message": "Method not allowed.",
    }


def test_api_error_carries_fields_and_headers(settings):
    app = create_app(settings)

    @app.get("/needs-auth")
    async def needs_auth() -> None:
        raise ApiError(
            401,
            "UNAUTHENTICATED",
            "Missing or invalid token.",
            fields={"authorization": "Bearer token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    response = TestClient(app).get("/needs-auth")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["fields"] == {"authorization": "Bearer token required"}


def test_empty_fields_are_omitted(client):
    assert "fields" not in client.get("/v1/nope").json()["error"]


def test_validation_errors_name_fields_without_the_location_prefix(settings):
    app = create_app(settings)

    @app.get("/items")
    async def items(limit: int) -> dict:
        return {"limit": limit}

    response = TestClient(app).get("/items", params={"limit": "many"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert set(error["fields"]) == {"limit"}


def test_overlong_messages_are_truncated_not_crashing(settings):
    app = create_app(settings)

    @app.get("/long")
    async def long() -> None:
        raise ApiError(400, "BAD_REQUEST", "x" * 2000, fields={"f": "y" * 2000})

    error = TestClient(app).get("/long").json()["error"]
    assert len(error["message"]) == 500
    assert len(error["fields"]["f"]) == 500


def test_openapi_documents_the_error_envelope(settings):
    schema = create_app(settings).openapi()
    responses = schema["paths"]["/v1/plans/{plan_id}"]["get"]["responses"]
    assert responses["501"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorEnvelope"
    )
