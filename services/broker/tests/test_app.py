from fastapi.testclient import TestClient

from app.config import BrokerSettings
from app.main import create_app


def test_health_returns_ok():
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_loads_shipped_policies():
    assert {rule.id for rule in create_app().state.policy.rules} >= {
        "github-read",
        "github-merge-deny",
        "default-deny-spend",
    }


def test_tool_calls_not_implemented_yet():
    response = TestClient(create_app()).post("/v1/tool-calls")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_approval_routes_are_unavailable_without_a_database():
    client = TestClient(create_app(BrokerSettings(_env_file=None)))
    response = client.get("/v1/approvals", params={"principal_id": "user-1"})
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "DATABASE_UNAVAILABLE",
            "message": "The broker database is not configured.",
        }
    }


def test_there_is_no_consume_route():
    client = TestClient(create_app(BrokerSettings(_env_file=None)))
    paths = set(client.app.openapi()["paths"])
    assert "/v1/approvals/{approval_id}/decisions" in paths
    assert not any("consume" in path for path in paths)
