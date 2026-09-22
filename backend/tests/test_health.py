from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_get_health_status_200():
    """Verify GET /health returns HTTP 200 status code."""
    response = client.get("/health")
    assert response.status_code == 200


def test_get_health_response_payload():
    """Verify GET /health returns exact JSON payload {"status": "ok"}."""
    response = client.get("/health")
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
