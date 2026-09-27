import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _v1_routes() -> list[tuple[str, str]]:
    app = create_app(Settings(_env_file=None, environment="test"))
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "x-1", path))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/v1/")
        for method in sorted(operations)
    ]


V1_ROUTES = _v1_routes()


def test_every_v1_route_is_covered():
    assert len(V1_ROUTES) == 14


@pytest.mark.parametrize(("method", "path"), V1_ROUTES)
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
