from fastapi.testclient import TestClient

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
