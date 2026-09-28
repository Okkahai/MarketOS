import pytest
from fastapi.testclient import TestClient

from app.api.routes import health


@pytest.fixture
def client():
    from app.main import create_app

    return TestClient(create_app())


def _ok() -> None:
    return None


def _fail() -> None:
    raise ConnectionError("could not connect to postgres://user:hunter2@db:5432")


def test_live_is_always_ok(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_ready_ok_when_all_checks_pass(client, monkeypatch):
    monkeypatch.setattr(health, "CHECKS", {"database": _ok, "redis": _ok})
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_503_and_names_the_failing_dependency(client, monkeypatch):
    monkeypatch.setattr(health, "CHECKS", {"database": _fail, "redis": _ok})
    response = client.get("/health/ready")
    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == {
        "status": "error",
        "latency_ms": body["checks"]["database"]["latency_ms"],
        "error": "ConnectionError",
    }
    assert body["checks"]["redis"]["status"] == "ok"


def test_ready_never_leaks_connection_strings(client, monkeypatch):
    monkeypatch.setattr(health, "CHECKS", {"database": _fail})
    assert "hunter2" not in client.get("/health/ready").text


def test_system_info_reports_paper_mode_without_secrets(client, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-secret")
    from app.core.config import get_settings

    get_settings.cache_clear()
    response = client.get("/api/v1/system/info")
    body = response.json()
    assert response.status_code == 200
    assert body["trading_mode"] == "paper"
    assert body["paper_initial_capital"] == "10000"
    assert body["providers_configured"]["tiingo"] is True
    assert "tiingo-secret" not in response.text
