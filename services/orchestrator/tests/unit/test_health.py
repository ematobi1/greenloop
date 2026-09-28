from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import create_app


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_ok_when_the_database_answers(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_readiness_is_503_when_database_not_configured(settings):
    response = TestClient(create_app(settings)).get("/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "not_configured"}}


def test_readiness_is_503_without_detail_when_database_is_down(settings, tmp_path):
    app = create_app(settings)
    unreachable = create_engine(f"sqlite:///{tmp_path / 'missing' / 'db.sqlite'}")
    app.state.session_factory = sessionmaker(bind=unreachable)
    response = TestClient(app).get("/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "unavailable"}}


def test_health_endpoints_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.get("/v1/health").status_code == 200
