"""Tests for Code Lens simulation engine and endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.agent.simulation import (
    SimulationRunResult,
    get_test_cases_for_repo,
    run_simulation,
)
from backend.app.main import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_demo_repo_test_cases():
    cases = get_test_cases_for_repo("demo_repo")
    assert len(cases) >= 4
    case_ids = [c.id for c in cases]
    assert "api_to_db_write" in case_ids
    assert "validation_path" in case_ids


def test_run_simulation_demo_repo():
    result = run_simulation("demo_repo")
    assert isinstance(result, SimulationRunResult)
    assert result.repository_id == "demo_repo"
    assert result.total >= 4
    assert result.passed >= 3
    assert result.total_duration_ms > 0
    assert len(result.cases) == result.total

    for case in result.cases:
        assert case.id
        assert case.name
        assert case.expected
        assert case.actual
        assert case.status in ("passed", "failed")
        assert case.duration_ms >= 0


def test_api_simulate_endpoint(client):
    resp = client.post("/api/simulate", json={"repository_id": "demo_repo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["repository_id"] == "demo_repo"
    assert data["total"] >= 4
    assert data["passed"] >= 3
    assert "cases" in data
    assert len(data["cases"]) == data["total"]


def test_api_simulate_invalid_repo_returns_422(client):
    resp = client.post("/api/simulate", json={"repository_id": "nonexistent_repo_xyz"})
    assert resp.status_code == 422


def test_api_simulate_cases_endpoint(client):
    resp = client.get("/api/simulate/cases?repository_id=demo_repo")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 4


def test_get_all_repos_have_specific_test_cases():
    """All 4 registered demo repositories must provide specific benchmark cases."""
    for repo_id in ("demo_ecommerce", "demo_auth", "demo_tasks", "demo_repo"):
        cases = get_test_cases_for_repo(repo_id)
        assert len(cases) >= 3, f"Repository {repo_id} should have at least 3 test cases."
        for c in cases:
            assert c.id
            assert c.name
            assert c.question
            assert c.expected_behavior


def test_run_simulation_ecommerce():
    """Run full simulation on E-Commerce API."""
    result = run_simulation("demo_ecommerce")
    assert result.repository_id == "demo_ecommerce"
    assert result.total == 3
    assert result.passed == 3, f"Expected 3 passed, got {result.passed} (cases: {[c.actual for c in result.cases]})"
    assert result.failed == 0


def test_run_simulation_auth():
    """Run full simulation on Authentication Service."""
    result = run_simulation("demo_auth")
    assert result.repository_id == "demo_auth"
    assert result.total == 3
    assert result.passed == 3, f"Expected 3 passed, got {result.passed} (cases: {[c.actual for c in result.cases]})"
    assert result.failed == 0


def test_run_simulation_tasks():
    """Run full simulation on Task Management API."""
    result = run_simulation("demo_tasks")
    assert result.repository_id == "demo_tasks"
    assert result.total == 3
    assert result.passed == 3, f"Expected 3 passed, got {result.passed} (cases: {[c.actual for c in result.cases]})"
    assert result.failed == 0


def test_repository_isolation_no_evidence_leakage(client):
    """Ensure investigations strictly search within the selected repository."""
    # 1. Investigate E-Commerce
    ecom_resp = client.post(
        "/api/investigate",
        json={
            "repository_id": "demo_ecommerce",
            "question": "Trace an order creation request from the API endpoint to the database write.",
        },
    )
    assert ecom_resp.status_code == 200
    ecom_data = ecom_resp.json()
    assert ecom_data["repository_id"] == "demo_ecommerce"
    assert "**Repository:** `demo_ecommerce`" in ecom_data["answer_summary"]
    # Evidence must come ONLY from demo_ecommerce files
    for ev in ecom_data["evidence"]:
        assert "users.py" not in ev["file"], f"Leaked users.py into demo_ecommerce: {ev}"
        assert any(
            x in ev["file"] for x in ("order", "product", "database", "validation", "routes")
        ), f"Unexpected file in ecommerce evidence: {ev['file']}"

    # 2. Investigate Auth
    auth_resp = client.post(
        "/api/investigate",
        json={
            "repository_id": "demo_auth",
            "question": "Trace a user login request from the API endpoint to credential verification.",
        },
    )
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    assert auth_data["repository_id"] == "demo_auth"
    assert "**Repository:** `demo_auth`" in auth_data["answer_summary"]
    for ev in auth_data["evidence"]:
        assert "order" not in ev["file"], f"Leaked order file into demo_auth: {ev}"
        assert any(
            x in ev["file"] for x in ("auth", "user", "routes", "database", "config")
        ), f"Unexpected file in auth evidence: {ev['file']}"

    # 3. Investigate Tasks
    tasks_resp = client.post(
        "/api/investigate",
        json={
            "repository_id": "demo_tasks",
            "question": "Trace a task creation request from the endpoint to the database write.",
        },
    )
    assert tasks_resp.status_code == 200
    tasks_data = tasks_resp.json()
    assert tasks_data["repository_id"] == "demo_tasks"
    assert "**Repository:** `demo_tasks`" in tasks_data["answer_summary"]
    for ev in tasks_data["evidence"]:
        assert "order" not in ev["file"], f"Leaked order file into demo_tasks: {ev}"
        assert any(
            x in ev["file"] for x in ("task", "validation", "routes", "database", "config")
        ), f"Unexpected file in tasks evidence: {ev['file']}"

