import pytest

from greenloop_contracts import Agent


@pytest.fixture
def auth(issue_token):
    return {"Authorization": f"Bearer {issue_token()}"}


def test_agents_require_a_token(client):
    assert client.get("/v1/agents").status_code == 401
    assert client.get("/v1/agents/echo-reference-agent").status_code == 401


def test_list_agents_returns_the_registry_in_the_page_shape(client, auth):
    body = client.get("/v1/agents", headers=auth).json()
    assert [a["agent_id"] for a in body["data"]] == [
        "echo-reference-agent",
        "failing-reference-agent",
    ]
    assert body["meta"] == {"total": 2, "limit": 50, "offset": 0}
    for item in body["data"]:
        Agent.model_validate(item)


def test_list_agents_filters_and_pages(client, auth):
    assert client.get("/v1/agents?domain=research", headers=auth).json()["meta"]["total"] == 0
    assert client.get("/v1/agents?status=active", headers=auth).json()["meta"]["total"] == 2
    page = client.get("/v1/agents?limit=1&offset=1", headers=auth).json()
    assert [a["agent_id"] for a in page["data"]] == ["failing-reference-agent"]
    assert page["meta"] == {"total": 2, "limit": 1, "offset": 1}


def test_an_unknown_domain_filter_is_a_validation_error(client, auth):
    assert client.get("/v1/agents?domain=astrology", headers=auth).status_code == 422


def test_get_agent(client, auth):
    body = client.get("/v1/agents/echo-reference-agent", headers=auth).json()
    assert body["agent_id"] == "echo-reference-agent"
    assert body["status"] == "active"


def test_an_unknown_agent_is_404(client, auth):
    response = client.get("/v1/agents/nope", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"
