from fastapi.testclient import TestClient

from app.api import health as health_module
from app.api.main import app

client = TestClient(app)


def test_health_reports_database_and_redis_status(monkeypatch):
    monkeypatch.setattr(health_module, "check_database_connection", lambda: (True, None))
    monkeypatch.setattr(health_module, "check_redis_connection", lambda: (True, None))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
        },
    }


def test_health_returns_503_when_dependency_is_down(monkeypatch):
    monkeypatch.setattr(health_module, "check_database_connection", lambda: (True, None))
    monkeypatch.setattr(health_module, "check_redis_connection", lambda: (False, "Redis unavailable"))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "services": {
            "database": {"status": "ok"},
            "redis": {"status": "error", "detail": "Redis unavailable"},
        },
    }


def test_validation_errors_use_consistent_json_shape():
    response = client.post(
        "/auth/register",
        json={"email": "invalid@example.com"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["message"] == "Request validation failed"
    assert payload["path"] == "/auth/register"
    assert payload["error"]["details"]
