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
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "broker": "not_configured"},
    }


def test_readiness_is_503_when_database_not_configured(settings):
    response = TestClient(create_app(settings)).get("/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "not_configured", "broker": "not_configured"},
    }


def test_readiness_is_503_without_detail_when_database_is_down(settings, tmp_path):
    app = create_app(settings)
    unreachable = create_engine(f"sqlite:///{tmp_path / 'missing' / 'db.sqlite'}")
    app.state.session_factory = sessionmaker(bind=unreachable)
    response = TestClient(app).get("/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "unavailable", "broker": "not_configured"},
    }


def test_health_endpoints_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.get("/v1/health").status_code == 200


def _transport(handler):
    import httpx2

    return httpx2.MockTransport(handler)


def test_the_broker_check_reports_status_only():
    import asyncio

    import httpx2

    from app.api.v1.health import broker_status

    def up(request):
        assert request.url.path == "/health"
        return httpx2.Response(200, json={"status": "ok"})

    def down(request):
        raise httpx2.ConnectError("refused")

    assert asyncio.run(broker_status("http://broker:8100/", _transport(up))) == "ok"
    assert (
        asyncio.run(broker_status("http://broker:8100", _transport(lambda r: httpx2.Response(500))))
        == "unavailable"
    )
    assert asyncio.run(broker_status("http://broker:8100", _transport(down))) == "unavailable"
    assert asyncio.run(broker_status(None)) == "not_configured"


def test_a_configured_broker_that_is_down_degrades_readiness(client, monkeypatch):
    from app.api.v1 import health

    async def down(url, transport=None):
        return "unavailable"

    monkeypatch.setattr(health, "broker_status", down)
    response = client.get("/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "broker": "unavailable"},
    }
    assert "http" not in response.text


def test_repeated_readiness_calls_share_one_broker_probe(client, monkeypatch):
    from app.api.v1 import health

    probes = []

    async def counted(url, transport=None):
        probes.append(url)
        return "unavailable"

    monkeypatch.setattr(health, "broker_status", counted)
    for _ in range(5):
        assert client.get("/v1/health").json()["checks"]["broker"] == "unavailable"
    assert len(probes) == 1

    monkeypatch.setattr(health, "BROKER_CACHE_SECONDS", 0.0)
    client.get("/v1/health")
    assert len(probes) == 2


def test_the_broker_probe_gives_up_after_its_timeout():
    import asyncio
    import time

    import httpx2

    from app.api.v1 import health

    async def slow(request):
        await asyncio.sleep(5)
        return httpx2.Response(200)

    started = time.monotonic()
    original = health.BROKER_TIMEOUT_SECONDS
    health.BROKER_TIMEOUT_SECONDS = 0.1
    try:
        assert (
            asyncio.run(health.broker_status("http://broker:8100", _transport(slow)))
            == "unavailable"
        )
    finally:
        health.BROKER_TIMEOUT_SECONDS = original
    assert time.monotonic() - started < 2
