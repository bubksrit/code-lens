"""Tests for POST /api/investigate and GET /api/repositories endpoints.

Uses FastAPI TestClient (no real server needed).  The test suite:
  - validates request/response schemas
  - validates repository_id whitelisting
  - validates empty/short questions are rejected
  - validates the full acceptance-criterion demo query
  - verifies evidence is source-grounded
  - verifies the call chain is present in the response
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture(scope="module")
def client():
    """TestClient wrapping the full FastAPI application."""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def investigation_result(client):
    """Run the demo investigation once and reuse across the module."""
    resp = client.post(
        "/api/investigate",
        json={
            "repository_id": "demo_repo",
            "question": "Trace an API request to the database write and identify where validation happens.",
        },
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# GET /api/repositories
# ---------------------------------------------------------------------------


def test_get_repositories_returns_200(client):
    resp = client.get("/api/repositories")
    assert resp.status_code == 200


def test_get_repositories_contains_demo_repo(client):
    resp = client.get("/api/repositories")
    data = resp.json()
    assert "repositories" in data
    assert "demo_repo" in data["repositories"]


def test_get_repositories_is_list(client):
    resp = client.get("/api/repositories")
    data = resp.json()
    assert isinstance(data["repositories"], list)


# ---------------------------------------------------------------------------
# POST /api/investigate — validation errors
# ---------------------------------------------------------------------------


def test_unknown_repository_id_returns_422(client):
    resp = client.post(
        "/api/investigate",
        json={"repository_id": "does_not_exist", "question": "Trace request to database"},
    )
    assert resp.status_code == 422


def test_empty_repository_id_returns_422(client):
    resp = client.post(
        "/api/investigate",
        json={"repository_id": "", "question": "Trace request to database"},
    )
    assert resp.status_code == 422


def test_missing_question_returns_422(client):
    resp = client.post(
        "/api/investigate",
        json={"repository_id": "demo_repo"},
    )
    assert resp.status_code == 422


def test_short_question_returns_422(client):
    """Questions shorter than 5 chars should be rejected by schema validation."""
    resp = client.post(
        "/api/investigate",
        json={"repository_id": "demo_repo", "question": "hi"},
    )
    assert resp.status_code == 422


def test_path_traversal_in_repo_id_rejected(client):
    resp = client.post(
        "/api/investigate",
        json={"repository_id": "../etc/passwd", "question": "Trace request to database"},
    )
    assert resp.status_code == 422


def test_missing_body_returns_422(client):
    resp = client.post("/api/investigate")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/investigate — successful response schema
# ---------------------------------------------------------------------------


def test_has_investigation_id(investigation_result):
    assert "investigation_id" in investigation_result
    assert investigation_result["investigation_id"]


def test_has_repository_id(investigation_result):
    assert investigation_result["repository_id"] == "demo_repo"


def test_has_question(investigation_result):
    assert "question" in investigation_result
    assert "API" in investigation_result["question"] or "api" in investigation_result["question"].lower()


def test_has_answer_summary(investigation_result):
    assert "answer_summary" in investigation_result
    assert len(investigation_result["answer_summary"]) > 20


def test_has_trace_list(investigation_result):
    assert "trace" in investigation_result
    assert isinstance(investigation_result["trace"], list)
    assert len(investigation_result["trace"]) > 0


def test_trace_steps_have_required_fields(investigation_result):
    for step in investigation_result["trace"]:
        assert "step_number" in step
        assert "tool_name" in step
        assert "input_params" in step
        assert "output_summary" in step
        assert "reason" in step
        assert "duration_ms" in step


def test_has_evidence_list(investigation_result):
    assert "evidence" in investigation_result
    assert isinstance(investigation_result["evidence"], list)
    assert len(investigation_result["evidence"]) > 0


def test_evidence_has_required_fields(investigation_result):
    for item in investigation_result["evidence"]:
        assert "evidence_id" in item
        assert "kind" in item
        assert "file" in item
        assert "start_line" in item
        assert "end_line" in item
        assert "source_text" in item
        assert "description" in item


def test_evidence_kind_values(investigation_result):
    valid_kinds = {"direct", "static_inference", "unresolved"}
    for item in investigation_result["evidence"]:
        assert item["kind"] in valid_kinds, f"Invalid evidence kind: {item['kind']}"


def test_evidence_line_ranges_valid(investigation_result):
    for item in investigation_result["evidence"]:
        assert item["start_line"] >= 1
        assert item["end_line"] >= item["start_line"]


def test_has_call_chain(investigation_result):
    assert "call_chain" in investigation_result
    assert isinstance(investigation_result["call_chain"], list)


def test_call_chain_steps_have_required_fields(investigation_result):
    for step in investigation_result["call_chain"]:
        assert "order" in step
        assert "symbol_id" in step
        assert "symbol_name" in step
        assert "file" in step
        assert "start_line" in step
        assert "end_line" in step
        assert "role" in step


def test_call_chain_ordered(investigation_result):
    chain = investigation_result["call_chain"]
    orders = [s["order"] for s in chain]
    assert orders == list(range(len(chain)))


def test_has_latency_ms(investigation_result):
    assert "latency_ms" in investigation_result
    assert investigation_result["latency_ms"] > 0


def test_has_grounding(investigation_result):
    assert "grounding" in investigation_result
    assert investigation_result["grounding"] in ("grounded", "partially_grounded", "ungrounded")


def test_has_total_steps(investigation_result):
    assert "total_steps" in investigation_result
    assert investigation_result["total_steps"] == len(investigation_result["trace"])


def test_has_validation_issues(investigation_result):
    assert "validation_issues" in investigation_result
    assert isinstance(investigation_result["validation_issues"], list)


# ---------------------------------------------------------------------------
# Acceptance criterion tests
# ---------------------------------------------------------------------------
# Acceptance test (verbatim from spec):
# Question: 'Trace an API request to the database write and identify where validation happens.'
# Repository: demo_repo.
# The system must:
#   - investigate the repository using multiple tools
#   - produce a trace
#   - identify the relevant multi-file call chain
#   - return source-grounded evidence


def test_acceptance_uses_multiple_tools(investigation_result):
    tool_names = {step["tool_name"] for step in investigation_result["trace"]}
    assert len(tool_names) >= 2, f"Expected >= 2 distinct tools, got: {tool_names}"


def test_acceptance_produces_investigation_trace(investigation_result):
    assert len(investigation_result["trace"]) >= 3, (
        f"Expected >= 3 trace steps, got {len(investigation_result['trace'])}"
    )


def test_acceptance_identifies_multi_file_call_chain(investigation_result):
    chain = investigation_result["call_chain"]
    assert len(chain) >= 3, f"Expected >= 3 chain hops, got {len(chain)}"
    files = {step["file"] for step in chain}
    assert len(files) >= 2, f"Expected chain to span >= 2 files, got: {files}"


def test_acceptance_call_chain_includes_database_node(investigation_result):
    roles = [step["role"] for step in investigation_result["call_chain"]]
    assert "database" in roles, f"Expected 'database' role in call chain, got: {roles}"


def test_acceptance_returns_source_grounded_evidence(investigation_result):
    direct = [e for e in investigation_result["evidence"] if e["kind"] == "direct"]
    assert len(direct) >= 1, "Expected at least 1 DIRECT evidence item"
    for item in direct:
        assert item["source_text"].strip(), f"DIRECT evidence {item['evidence_id']} has empty source_text"
        assert item["file"]
        assert item["start_line"] >= 1


def test_acceptance_evidence_files_relative(investigation_result):
    """All evidence files should be relative paths (no absolute, no traversal)."""
    for item in investigation_result["evidence"]:
        assert not item["file"].startswith("/"), f"Evidence file must be relative: {item['file']}"
        assert ".." not in item["file"], f"Evidence file must not traverse: {item['file']}"


def test_acceptance_answer_references_findings(investigation_result):
    """Answer should mention call chain or relevant symbols."""
    summary = investigation_result["answer_summary"].lower()
    assert any(
        term in summary
        for term in ("call chain", "route", "endpoint", "service", "database", "symbol", "validation", "auth")
    ), f"Answer summary doesn't reference investigation findings: {summary[:300]}"


def test_answer_summary_displays_repository_and_question(investigation_result):
    """Answer summary must explicitly state the analyzed repository and question."""
    summary = investigation_result["answer_summary"]
    assert "**Repository:** `demo_repo`" in summary
    assert "**Question:** Trace an API request to the database write and identify where validation happens." in summary


def test_get_repositories_returns_items_metadata(client):
    """GET /api/repositories must return items with full metadata."""
    resp = client.get("/api/repositories")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) >= 1
    demo_meta = next((item for item in data["items"] if item["id"] == "demo_repo"), None)
    assert demo_meta is not None
    assert demo_meta["name"] in ("demo_repo — multi-layer Python app", "Multi-Layer Python App")
    assert demo_meta["path"] == "data/demo_repo"
    assert "description" in demo_meta


def test_register_repository_success_and_investigate(client, tmp_path):
    """Dynamically register a new repository and run an investigation against it."""
    # Create a small valid Python repo in tmp_path
    repo_dir = tmp_path / "custom_service"
    repo_dir.mkdir()
    py_file = repo_dir / "service.py"
    py_file.write_text(
        "def process_order(order_id: str):\n"
        "    \"\"\"Process an order.\"\"\"\n"
        "    return execute_save(order_id)\n\n"
        "def execute_save(order_id: str):\n"
        "    return True\n",
        encoding="utf-8",
    )

    # 1. Register via POST /api/repositories
    reg_resp = client.post(
        "/api/repositories",
        json={
            "repository_id": "custom_service",
            "path": str(repo_dir),
            "name": "Custom Order Service",
            "description": "Order processing test service",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["id"] == "custom_service"
    assert reg_data["name"] == "Custom Order Service"

    # 2. Check it appears in GET /api/repositories
    list_resp = client.get("/api/repositories")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert "custom_service" in list_data["repositories"]
    assert any(item["id"] == "custom_service" for item in list_data["items"])

    # 3. Investigate this newly registered repository
    inv_resp = client.post(
        "/api/investigate",
        json={
            "repository_id": "custom_service",
            "question": "Trace process_order to execute_save",
        },
    )
    assert inv_resp.status_code == 200
    inv_data = inv_resp.json()
    assert inv_data["repository_id"] == "custom_service"
    assert "**Repository:** `custom_service`" in inv_data["answer_summary"]
    assert len(inv_data["trace"]) > 0


def test_register_repository_invalid_path_fails(client):
    """Registering a non-existent path must return HTTP 400."""
    resp = client.post(
        "/api/repositories",
        json={
            "repository_id": "invalid_repo",
            "path": "/path/to/nonexistent/directory/xyz",
        },
    )
    assert resp.status_code == 400
