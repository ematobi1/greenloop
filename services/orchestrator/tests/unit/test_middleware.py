import re

import pytest
from fastapi.testclient import TestClient

from app.core.middleware import REQUEST_ID_HEADER, is_allowed_host
from app.main import create_app
from greenloop_contracts import ErrorDetail


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.1:8787", True),
        ("localhost:5173", True),
        ("evil.com", False),
        ("127.0.0.1.evil.com", False),
        ("evil.com:127.0.0.1", False),
        ("", False),
        ("[::1]:8787", False),
        ("127.0.0.1:notaport", False),
        ("LOCALHOST", True),
    ],
)
def test_is_allowed_host(host, expected):
    assert is_allowed_host(host, ["127.0.0.1", "localhost"]) is expected


class TestHostAllowlist:
    def test_foreign_host_is_rejected_with_error_envelope(self, client):
        response = client.get("/health", headers={"Host": "evil.example.com"})
        assert response.status_code == 400
        error = ErrorDetail.model_validate(response.json()["error"])
        assert error.code == "INVALID_HOST"

    def test_foreign_host_is_rejected_on_every_route(self, client):
        response = client.get("/v1/plans/x-1", headers={"Host": "rebind.example.com"})
        assert response.status_code == 400

    def test_allowed_host_passes(self, client):
        assert client.get("/health").status_code == 200

    def test_default_allowlist_is_loopback_only(self, settings):
        default = type(settings)(_env_file=None)
        assert default.allowed_hosts == ["127.0.0.1", "localhost"]


class TestRequestId:
    def test_every_response_carries_a_request_id(self, client):
        response = client.get("/health")
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])

    def test_request_ids_are_unique(self, client):
        ids = {client.get("/health").headers[REQUEST_ID_HEADER] for _ in range(20)}
        assert len(ids) == 20

    def test_rejected_and_failed_requests_also_carry_it(self, settings):
        app = create_app(settings)

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("secret internal detail")

        client = TestClient(app, raise_server_exceptions=False)
        failed = client.get("/boom")
        rejected = client.get("/health", headers={"Host": "evil.example.com"})
        assert failed.status_code == 500
        assert "secret internal detail" not in failed.text
        assert REQUEST_ID_HEADER in failed.headers
        assert REQUEST_ID_HEADER in rejected.headers

    def test_client_supplied_request_id_is_not_trusted(self, client):
        response = client.get("/health", headers={REQUEST_ID_HEADER: "attacker-chosen"})
        assert response.headers[REQUEST_ID_HEADER] != "attacker-chosen"


class TestCors:
    def test_configured_origin_gets_cors_headers(self, client):
        response = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_unknown_origin_gets_no_cors_headers(self, client):
        response = client.get("/health", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_request_id_is_exposed_to_browsers(self, client):
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert "X-Request-ID" in response.headers["access-control-expose-headers"]
