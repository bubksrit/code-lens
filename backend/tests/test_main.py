from fastapi.testclient import TestClient
from backend.app.main import app, create_app


def test_application_startup():
    """Verify application instance initializes without error."""
    test_app = create_app()
    assert test_app is not None
    assert test_app.title == "PRISM Agentic Code Intelligence"


def test_openapi_schema_generation():
    """Verify OpenAPI schema is accessible and includes expected routes."""
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "paths" in schema
    assert "/health" in schema["paths"]
