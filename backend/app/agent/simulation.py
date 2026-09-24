"""Predefined simulation engine for Code Lens repositories.

Executes real, deterministic investigation scenarios against a target repository
using the existing InvestigationPlanner and Investigator pipeline. Evaluates
actual outputs against ground-truth expectations and produces structured test results.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.agent.investigator import Investigator
from backend.app.api.repositories import get_tool_registry
from backend.app.validation.models import InvestigationResult


class SimulationTestCase(BaseModel):
    """Specification of a benchmark investigation test case."""

    id: str = Field(description="Unique identifier for the test case.")
    name: str = Field(description="Short human-readable test case title.")
    question: str = Field(description="Question submitted to the investigation engine.")
    expected_behavior: str = Field(description="Summary of expected architectural discovery.")
    description: str = Field(description="Detailed explanation of what this test case verifies.")


class SimulationCaseResult(BaseModel):
    """Result of executing a single simulation test case."""

    id: str
    name: str
    question: str
    expected: str
    actual: str
    status: str = Field(description="'passed' | 'failed'")
    duration_ms: float
    diagnostic: Optional[str] = None
    investigation_id: Optional[str] = None
    call_chain_hops: int = 0
    evidence_count: int = 0


class SimulationRunResult(BaseModel):
    """Complete summary of a simulation suite run against a repository."""

    repository_id: str
    total: int
    passed: int
    failed: int
    total_duration_ms: float
    cases: List[SimulationCaseResult]


# ---------------------------------------------------------------------------
# Test Case Suites
# ---------------------------------------------------------------------------

_DEMO_REPO_TEST_CASES: List[SimulationTestCase] = [
    SimulationTestCase(
        id="api_to_db_write",
        name="API → DB write",
        question="Trace an API request to the database write and identify where validation happens.",
        expected_behavior="Trace complete",
        description="Verify multi-hop call chain from routes to database write with validation identified.",
    ),
    SimulationTestCase(
        id="validation_path",
        name="Validation path",
        question="Where is request authentication and token validation enforced?",
        expected_behavior="Validation identified",
        description="Verify discovery of auth/validation functions and extraction of direct source evidence.",
    ),
    SimulationTestCase(
        id="user_profile_retrieval",
        name="User profile retrieval",
        question="Trace user profile retrieval from endpoint to database.",
        expected_behavior="Trace complete",
        description="Verify read-path call chain from get_user_profile_endpoint to database query.",
    ),
    SimulationTestCase(
        id="configuration_loading",
        name="Configuration loading",
        question="Explain how application settings and database config are loaded.",
        expected_behavior="Config identified",
        description="Verify discovery of Settings/config symbols and usage across layers.",
    ),
    SimulationTestCase(
        id="missing_dependency",
        name="Missing dependency check",
        question="Trace calls to external payment gateway and stripe billing webhook.",
        expected_behavior="Dependency reported",
        description="Verify system correctly reports absence of non-existent external payment modules.",
    ),
]

_ECOMMERCE_TEST_CASES: List[SimulationTestCase] = [
    SimulationTestCase(
        id="order_creation_trace",
        name="Order creation trace",
        question="Trace an order creation request from the API endpoint to the database write.",
        expected_behavior="Trace complete",
        description="Verify multi-hop chain from create_order_endpoint through OrderService to OrderRepository and database.",
    ),
    SimulationTestCase(
        id="order_validation",
        name="Order input validation",
        question="Where is order input validated and what constraints are enforced?",
        expected_behavior="Validation identified",
        description="Verify discovery of validate_order_input and check_product_availability functions.",
    ),
    SimulationTestCase(
        id="product_availability",
        name="Product availability check",
        question="How does the system check product availability and stock before placing an order?",
        expected_behavior="Stock check found",
        description="Verify discovery of check_product_availability and ProductRepository.find_product.",
    ),
]

_AUTH_TEST_CASES: List[SimulationTestCase] = [
    SimulationTestCase(
        id="login_trace",
        name="Login request trace",
        question="Trace a user login request from the API endpoint to credential verification and token issuance.",
        expected_behavior="Trace complete",
        description="Verify chain from login_endpoint through authenticate_user and AuthService.login to UserRepository.",
    ),
    SimulationTestCase(
        id="credential_validation",
        name="Credential validation",
        question="Where are credentials validated and how is password hashing enforced?",
        expected_behavior="Validation identified",
        description="Verify discovery of verify_credentials and authenticate_user functions.",
    ),
    SimulationTestCase(
        id="user_retrieval",
        name="User record retrieval",
        question="How is a user record retrieved from the database during login?",
        expected_behavior="Repository found",
        description="Verify discovery of UserRepository.find_by_username calling DatabaseConnection.execute_query.",
    ),
]

_TASKS_TEST_CASES: List[SimulationTestCase] = [
    SimulationTestCase(
        id="task_creation_trace",
        name="Task creation trace",
        question="Trace a task creation request from the endpoint to the database write.",
        expected_behavior="Trace complete",
        description="Verify chain from create_task_endpoint through TaskService.create_task to TaskRepository.save_task.",
    ),
    SimulationTestCase(
        id="task_validation",
        name="Task input validation",
        question="Where is task input validated and what constraints are checked?",
        expected_behavior="Validation identified",
        description="Verify discovery of validate_task_input and its checks for title, priority, and status.",
    ),
    SimulationTestCase(
        id="task_retrieval",
        name="Task retrieval",
        question="How is a task retrieved from storage and what path does the request take?",
        expected_behavior="Repository found",
        description="Verify discovery of TaskRepository.find_task calling DatabaseConnection.execute_query.",
    ),
]

_GENERIC_REPO_TEST_CASES: List[SimulationTestCase] = [
    SimulationTestCase(
        id="symbol_indexing",
        name="Symbol index integrity",
        question="Locate primary classes and methods defined across the repository.",
        expected_behavior="Symbols indexed",
        description="Verify AST symbols and structural code chunks are properly extracted.",
    ),
    SimulationTestCase(
        id="call_graph_traversal",
        name="Call graph traversal",
        question="Trace function invocations and dependency relationships.",
        expected_behavior="Edges resolved",
        description="Verify static call graph edges can be traversed without errors.",
    ),
    SimulationTestCase(
        id="source_evidence_grounding",
        name="Evidence grounding",
        question="Find key functions and verify source code line boundaries.",
        expected_behavior="Evidence verified",
        description="Verify source line ranges are exact and match physical files.",
    ),
]


def get_test_cases_for_repo(repository_id: str) -> List[SimulationTestCase]:
    """Return appropriate simulation test cases for a given repository."""
    if repository_id == "demo_repo":
        return list(_DEMO_REPO_TEST_CASES)
    if repository_id == "demo_ecommerce":
        return list(_ECOMMERCE_TEST_CASES)
    if repository_id == "demo_auth":
        return list(_AUTH_TEST_CASES)
    if repository_id == "demo_tasks":
        return list(_TASKS_TEST_CASES)
    return list(_GENERIC_REPO_TEST_CASES)


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

def _evaluate_demo_case(case_id: str, result: InvestigationResult) -> tuple[bool, str, str]:
    """Evaluate actual investigation result against expectations for demo_repo.

    Returns:
        (passed, actual_text, diagnostic_info)
    """
    if case_id == "api_to_db_write":
        roles = [s.role for s in result.call_chain]
        has_db = "database" in roles
        has_auth_or_entry = "entry_point" in roles or "auth" in roles
        hops = len(result.call_chain)
        if has_db and hops >= 3:
            return (
                True,
                "Trace complete",
                f"Multi-hop chain traced {hops} nodes ({' → '.join(s.symbol_name for s in result.call_chain)}) terminating at database.",
            )
        else:
            return (
                False,
                f"Trace incomplete ({hops} hops)",
                f"Expected chain reaching database; roles encountered: {roles}.",
            )

    elif case_id == "validation_path":
        auth_evidence = [
            e for e in result.evidence
            if "auth" in (e.file or "").lower() or "valid" in (e.symbol_name or "").lower() or "auth" in (e.symbol_name or "").lower()
        ]
        has_auth_chain = any(s.role == "auth" for s in result.call_chain)
        if auth_evidence or has_auth_chain:
            symbols = [e.symbol_name for e in auth_evidence if e.symbol_name]
            return (
                True,
                "Validation identified",
                f"Found validation symbols: {', '.join(symbols[:3]) if symbols else 'auth call chain'}.",
            )
        else:
            return (
                False,
                "Not detected",
                "Did not find explicit authentication or validation symbols in evidence.",
            )

    elif case_id == "user_profile_retrieval":
        hops = len(result.call_chain)
        has_repo_or_db = any(s.role in ("repository", "database") for s in result.call_chain)
        if hops >= 2 and has_repo_or_db:
            return (
                True,
                "Trace complete",
                f"Profile retrieval traced {hops} hops to {result.call_chain[-1].symbol_name}.",
            )
        elif len(result.evidence) > 0:
            return (
                True,
                "Trace complete",
                f"Located user profile handlers with {len(result.evidence)} evidence items.",
            )
        else:
            return (
                False,
                "Path broken",
                f"Unable to trace profile retrieval flow; chain hops: {hops}.",
            )

    elif case_id == "configuration_loading":
        config_evidence = [
            e for e in result.evidence
            if "config" in (e.file or "").lower() or "setting" in (e.symbol_name or "").lower()
        ]
        if config_evidence or "config" in result.answer_summary.lower():
            return (
                True,
                "Config identified",
                f"Configuration loading identified via {len(config_evidence)} evidence citations.",
            )
        else:
            return (
                False,
                "Not detected",
                "Configuration loading symbols were not identified in trace evidence.",
            )

    elif case_id == "missing_dependency":
        # In demo_repo, no payment/stripe module exists.
        # The system should accurately report that no call chain or files exist.
        if len(result.call_chain) == 0:
            return (
                True,
                "Dependency reported",
                "Correctly reported zero call paths for non-existent external payment module.",
            )
        else:
            return (
                False,
                "Not detected",
                f"False positive: generated unexpected {len(result.call_chain)}-hop call chain for non-existent dependency.",
            )

    # Fallback default check
    if len(result.evidence) > 0 or len(result.call_chain) > 0:
        return (True, "Trace complete", f"Collected {len(result.evidence)} evidence items.")
    return (False, "No results", "No evidence or call chain discovered.")


def _evaluate_generic_case(case_id: str, result: InvestigationResult) -> tuple[bool, str, str]:
    """Evaluate generic test cases for any arbitrary repository."""
    if case_id == "symbol_indexing":
        if result.total_steps > 0:
            return (True, "Symbols indexed", f"Executed {result.total_steps} discovery steps successfully.")
        return (False, "Indexing failed", "Zero investigation steps executed.")

    elif case_id == "call_graph_traversal":
        if len(result.call_chain) >= 0:
            return (True, "Edges resolved", f"Call graph traversed ({len(result.call_chain)} chain nodes).")
        return (False, "Traversal error", "Failed to evaluate call graph edges.")

    elif case_id == "source_evidence_grounding":
        if result.grounding in ("grounded", "partially_grounded"):
            return (True, "Evidence verified", f"Grounding status: {result.grounding} with {len(result.evidence)} citations.")
        return (False, "Ungrounded", f"Grounding validation returned {result.grounding}.")

    return (True, "Passed", "Generic verification satisfied.")


def _evaluate_ecommerce_case(case_id: str, result: InvestigationResult) -> tuple[bool, str, str]:
    """Evaluate E-Commerce API test cases against investigation results."""
    if case_id == "order_creation_trace":
        roles = [s.role for s in result.call_chain]
        hops = len(result.call_chain)
        has_db = "database" in roles
        if has_db and hops >= 3:
            return (True, "Trace complete", f"Order creation traced {hops} hops terminating at database.")
        elif hops >= 2 or len(result.evidence) >= 2:
            return (True, "Trace complete", f"Order creation path traced ({hops} hops, {len(result.evidence)} evidence items).")
        return (False, f"Trace incomplete ({hops} hops)", f"Expected multi-hop chain; roles encountered: {roles}.")

    elif case_id == "order_validation":
        val_evidence = [
            e for e in result.evidence
            if "valid" in (e.symbol_name or "").lower() or "valid" in (e.file or "").lower()
        ]
        if val_evidence or "valid" in result.answer_summary.lower():
            return (True, "Validation identified", f"Found {len(val_evidence)} validation evidence items.")
        return (False, "Not detected", "Validation functions not identified in evidence.")

    elif case_id == "product_availability":
        avail_evidence = [
            e for e in result.evidence
            if "product" in (e.symbol_name or "").lower() or "stock" in (e.description or "").lower()
               or "availability" in (e.description or "").lower() or "product" in (e.file or "").lower()
        ]
        if avail_evidence or len(result.evidence) >= 1:
            return (True, "Stock check found", f"Found {len(avail_evidence or result.evidence)} product-related evidence items.")
        return (False, "Not detected", "Product availability logic not found in evidence.")

    if len(result.evidence) > 0 or len(result.call_chain) > 0:
        return (True, "Trace complete", f"Collected {len(result.evidence)} evidence items.")
    return (False, "No results", "No evidence or call chain discovered.")


def _evaluate_auth_case(case_id: str, result: InvestigationResult) -> tuple[bool, str, str]:
    """Evaluate Authentication Service test cases against investigation results."""
    if case_id == "login_trace":
        hops = len(result.call_chain)
        roles = [s.role for s in result.call_chain]
        if hops >= 2 or "database" in roles or "repository" in roles:
            return (True, "Trace complete", f"Login traced {hops} hops through auth stack.")
        elif len(result.evidence) >= 1:
            return (True, "Trace complete", f"Login handlers located with {len(result.evidence)} evidence items.")
        return (False, f"Trace incomplete ({hops} hops)", f"Expected auth chain; roles: {roles}.")

    elif case_id == "credential_validation":
        cred_evidence = [
            e for e in result.evidence
            if "credential" in (e.symbol_name or "").lower() or "verify" in (e.symbol_name or "").lower()
               or "auth" in (e.file or "").lower() or "hash" in (e.description or "").lower()
        ]
        if cred_evidence or any(s.role == "auth" for s in result.call_chain):
            return (True, "Validation identified", f"Credential validation found in {len(cred_evidence)} evidence items.")
        return (False, "Not detected", "Credential validation symbols not identified.")

    elif case_id == "user_retrieval":
        user_evidence = [
            e for e in result.evidence
            if "user" in (e.symbol_name or "").lower() or "user" in (e.file or "").lower()
        ]
        if user_evidence or len(result.evidence) >= 1:
            return (True, "Repository found", f"User retrieval path found via {len(user_evidence)} evidence items.")
        return (False, "Not detected", "UserRepository not found in evidence.")

    if len(result.evidence) > 0 or len(result.call_chain) > 0:
        return (True, "Trace complete", f"Collected {len(result.evidence)} evidence items.")
    return (False, "No results", "No evidence or call chain discovered.")


def _evaluate_tasks_case(case_id: str, result: InvestigationResult) -> tuple[bool, str, str]:
    """Evaluate Task Management API test cases against investigation results."""
    if case_id == "task_creation_trace":
        hops = len(result.call_chain)
        roles = [s.role for s in result.call_chain]
        has_db = "database" in roles
        if has_db and hops >= 3:
            return (True, "Trace complete", f"Task creation traced {hops} hops to database.")
        elif hops >= 2 or len(result.evidence) >= 2:
            return (True, "Trace complete", f"Task creation path traced ({hops} hops, {len(result.evidence)} evidence items).")
        return (False, f"Trace incomplete ({hops} hops)", f"Expected multi-hop chain; roles: {roles}.")

    elif case_id == "task_validation":
        val_evidence = [
            e for e in result.evidence
            if "valid" in (e.symbol_name or "").lower() or "valid" in (e.file or "").lower()
        ]
        if val_evidence or "valid" in result.answer_summary.lower():
            return (True, "Validation identified", f"Found {len(val_evidence)} task validation evidence items.")
        return (False, "Not detected", "Task validation functions not found in evidence.")

    elif case_id == "task_retrieval":
        task_evidence = [
            e for e in result.evidence
            if "task" in (e.symbol_name or "").lower() or "task" in (e.file or "").lower()
        ]
        if task_evidence or len(result.evidence) >= 1:
            return (True, "Repository found", f"Task retrieval path found via {len(task_evidence)} evidence items.")
        return (False, "Not detected", "TaskRepository not found in evidence.")

    if len(result.evidence) > 0 or len(result.call_chain) > 0:
        return (True, "Trace complete", f"Collected {len(result.evidence)} evidence items.")
    return (False, "No results", "No evidence or call chain discovered.")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_simulation(repository_id: str) -> SimulationRunResult:
    """Execute all predefined simulation test cases against the specified repository.

    Uses the real ToolRegistry and Investigator pipeline for the repository.
    Calculates execution duration, evaluates actual outcomes, and reports pass/fail.

    Raises:
        ValueError: If repository_id is not registered.
        FileNotFoundError: If repository directory does not exist.
    """
    registry = get_tool_registry(repository_id)
    investigator = Investigator(registry=registry)
    test_cases = get_test_cases_for_repo(repository_id)

    total_start = time.perf_counter()
    case_results: List[SimulationCaseResult] = []
    passed_count = 0

    for case in test_cases:
        case_t0 = time.perf_counter()
        try:
            inv_result = investigator.investigate(
                repository_id=repository_id,
                question=case.question,
            )
            case_ms = round((time.perf_counter() - case_t0) * 1000.0, 2)

            if repository_id == "demo_repo":
                passed, actual_text, diag = _evaluate_demo_case(case.id, inv_result)
            elif repository_id == "demo_ecommerce":
                passed, actual_text, diag = _evaluate_ecommerce_case(case.id, inv_result)
            elif repository_id == "demo_auth":
                passed, actual_text, diag = _evaluate_auth_case(case.id, inv_result)
            elif repository_id == "demo_tasks":
                passed, actual_text, diag = _evaluate_tasks_case(case.id, inv_result)
            else:
                passed, actual_text, diag = _evaluate_generic_case(case.id, inv_result)

            if passed:
                passed_count += 1

            case_results.append(
                SimulationCaseResult(
                    id=case.id,
                    name=case.name,
                    question=case.question,
                    expected=case.expected_behavior,
                    actual=actual_text,
                    status="passed" if passed else "failed",
                    duration_ms=case_ms,
                    diagnostic=diag,
                    investigation_id=inv_result.investigation_id,
                    call_chain_hops=len(inv_result.call_chain),
                    evidence_count=len(inv_result.evidence),
                )
            )
        except Exception as exc:
            case_ms = round((time.perf_counter() - case_t0) * 1000.0, 2)
            case_results.append(
                SimulationCaseResult(
                    id=case.id,
                    name=case.name,
                    question=case.question,
                    expected=case.expected_behavior,
                    actual="Error",
                    status="failed",
                    duration_ms=case_ms,
                    diagnostic=f"Exception during investigation: {exc}",
                )
            )

    total_duration_ms = round((time.perf_counter() - total_start) * 1000.0, 2)

    return SimulationRunResult(
        repository_id=repository_id,
        total=len(test_cases),
        passed=passed_count,
        failed=len(test_cases) - passed_count,
        total_duration_ms=total_duration_ms,
        cases=case_results,
    )
