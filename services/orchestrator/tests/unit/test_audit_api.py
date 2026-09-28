import pytest
from fastapi.testclient import TestClient

from app.audit import recorder
from app.core import tokens
from app.core.config import Settings
from app.main import create_app
from greenloop_contracts import AuditOutcome, AuditRecord

URL = "/v1/audit-records"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed(session_factory):
    def write(*records: AuditRecord) -> None:
        with session_factory() as session:
            for entry in records:
                recorder.record(session, entry)
            session.commit()

    return write


def _ids(response) -> list[str]:
    return [item["audit_id"] for item in response.json()["data"]]


def _own_ids(response) -> list[str]:
    return [item for item in _ids(response) if not item.startswith("aud-")]


def test_missing_token_is_401_with_bearer_challenge(client):
    response = client.get(URL)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("header", ["Bearer glt_wrong", "Basic dXNlcjpwYXNz", "Bearer "])
def test_invalid_credentials_are_401(client, issue_token, header):
    issue_token()
    response = client.get(URL, headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_revoked_token_is_401(client, session_factory):
    with session_factory() as session:
        tokens.create_principal(session, "user-1", "User")
        token_id, token = tokens.issue_token(session, "user-1", "laptop")
        session.commit()
    assert client.get(URL, headers=_auth(token)).status_code == 200
    with session_factory() as session:
        tokens.revoke_token(session, token_id)
        session.commit()
    assert client.get(URL, headers=_auth(token)).status_code == 401


def test_lists_only_the_callers_records_newest_first(client, issue_token, seed, make_audit):
    token = issue_token("user-1")
    issue_token("user-2")
    seed(
        make_audit("a-old", minute=1),
        make_audit("a-new", minute=5),
        make_audit("b-secret", principal_id="user-2", minute=9),
    )
    response = client.get(URL, headers=_auth(token))
    assert response.status_code == 200
    assert _own_ids(response) == ["a-new", "a-old"]
    assert "b-secret" not in _ids(response)


def test_response_shape_matches_the_contract(client, issue_token, seed, make_audit):
    token = issue_token()
    seed(make_audit("a-1"))
    body = client.get(URL, headers=_auth(token)).json()
    assert set(body) == {"data", "meta"}
    item = next(entry for entry in body["data"] if entry["audit_id"] == "a-1")
    assert AuditRecord.model_validate(item).details == {"note": "synthetic"}
    assert item["occurred_at"] == "2026-09-28T12:00:00Z"


def test_pagination_reports_total_and_window(client, issue_token, seed, make_audit):
    token = issue_token()
    seed(*(make_audit(f"a-{minute}", minute=minute) for minute in range(5)))
    body = client.get(
        URL, headers=_auth(token), params={"limit": 2, "offset": 1, "correlation_id": "req-1"}
    ).json()
    assert body["meta"] == {"total": 5, "limit": 2, "offset": 1}
    assert [item["audit_id"] for item in body["data"]] == ["a-3", "a-2"]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"outcome": "maybe"}]
)
def test_out_of_range_query_params_are_422(client, issue_token, params):
    response = client.get(URL, headers=_auth(issue_token()), params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_filters_by_outcome_and_correlation_id(client, issue_token, seed, make_audit):
    token = issue_token()
    seed(
        make_audit("a-allowed"),
        make_audit("a-denied", outcome=AuditOutcome.DENIED),
        make_audit("a-other-request", correlation_id="req-2"),
    )
    denied = client.get(URL, headers=_auth(token), params={"outcome": "denied"})
    assert _ids(denied) == ["a-denied"]
    other = client.get(URL, headers=_auth(token), params={"correlation_id": "req-2"})
    assert _ids(other) == ["a-other-request"]


def test_unconfigured_database_is_503_not_a_crash(settings):
    client = TestClient(create_app(settings))
    response = client.get(URL, headers=_auth("glt_anything"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_failed_auth_never_logs_the_presented_token(client, caplog):
    presented = "glt_secret-looking-presented-token"
    client.get(URL, headers=_auth(presented))
    assert "authentication_failed" in caplog.text
    assert presented not in caplog.text


def test_settings_default_has_no_database(settings: Settings):
    assert create_app(settings).state.session_factory is None
