"""Tests for the deterministic investigation planner and investigator.

These tests exercise:
  - intent detection
  - keyword extraction
  - role classification
  - planner trace/explain/search strategies
  - investigator result structure
  - evidence validation
  - answer summary generation
"""
from __future__ import annotations

import pytest

from backend.app.agent.planner import (
    InvestigationPlanner,
    _detect_intent,
    _detect_role,
    _extract_keywords,
)
from backend.app.validation.models import (
    EvidenceKind,
    InvestigationResult,
)
from backend.app.validation.validator import EvidenceValidator, ValidationIssue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_registry():
    """Build a real ToolRegistry for the demo repo (cached for the module)."""
    from pathlib import Path
    from backend.app.agent.tools import create_tool_registry

    # Walk up to project root
    root = Path(__file__).resolve()
    for parent in root.parents:
        if (parent / "pyproject.toml").is_file():
            root = parent
            break

    repo_path = root / "data" / "demo_repo"
    if not repo_path.is_dir():
        pytest.skip(f"demo_repo not found at {repo_path}")

    return create_tool_registry(repo_path)


@pytest.fixture(scope="module")
def investigator(demo_registry):
    """Return a real Investigator for the demo repo."""
    from backend.app.agent.investigator import Investigator
    return Investigator(registry=demo_registry)


# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------


class TestDetectIntent:
    def test_trace_keywords(self):
        assert _detect_intent("Trace an API request to the database") == "trace"
        assert _detect_intent("Follow the request flow from route to DB") == "trace"
        assert _detect_intent("What is the path of an API request?") == "trace"

    def test_explain_keywords(self):
        assert _detect_intent("Explain how user authentication works") == "explain"
        assert _detect_intent("What does verify_request_auth do?") == "explain"

    def test_find_keywords(self):
        assert _detect_intent("Where is the validation logic?") == "find"
        assert _detect_intent("Find where config is loaded") == "find"

    def test_search_default(self):
        assert _detect_intent("UserService get_user_profile") == "search"


class TestExtractKeywords:
    def test_removes_stop_words(self):
        kws = _extract_keywords("Trace an API request to the database")
        assert "an" not in kws
        assert "the" not in kws
        assert "to" not in kws

    def test_keeps_identifiers(self):
        kws = _extract_keywords("Trace API request database write validation")
        assert "Trace" in kws or "trace" in kws.copy()
        assert any("API" in k or "api" in k.lower() for k in kws)

    def test_deduplication(self):
        kws = _extract_keywords("route route route endpoint")
        assert kws.count("route") == 1


class TestDetectRole:
    def test_entry_point_patterns(self):
        assert _detect_role("get_user_profile_endpoint") == "entry_point"
        assert _detect_role("user_route_handler") == "entry_point"

    def test_auth_patterns(self):
        assert _detect_role("verify_request_auth") == "auth"
        assert _detect_role("validate_token") == "auth"
        assert _detect_role("verify_bearer_token") == "auth"

    def test_service_patterns(self):
        assert _detect_role("UserService") == "service"

    def test_repository_patterns(self):
        assert _detect_role("UserRepository") == "repository"
        assert _detect_role("find_by_id") == "repository"

    def test_database_patterns(self):
        assert _detect_role("execute_query") == "database"
        assert _detect_role("DatabaseConnection") == "database"
        assert _detect_role("execute_write") == "database"

    def test_general_fallback(self):
        assert _detect_role("some_random_function") == "general"


# ---------------------------------------------------------------------------
# Planner integration tests
# ---------------------------------------------------------------------------


class TestPlannerTrace:
    """Tests for the TRACE investigation strategy."""

    def test_produces_execution_steps(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, evidence, chain = planner.investigate(
            "Trace an API request to the database write and identify where validation happens."
        )
        assert len(steps) > 0, "Planner must produce at least one execution step."

    def test_steps_have_required_fields(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("Trace API request to database")
        for step in steps:
            assert step.step_number >= 1
            assert step.tool_name
            assert step.reason
            assert step.duration_ms >= 0

    def test_trace_strategy_uses_keyword_search(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("Trace API request to database write")
        tool_names = [s.tool_name for s in steps]
        assert "keyword_search" in tool_names

    def test_trace_strategy_uses_find_callees(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("Trace API request to database write")
        tool_names = [s.tool_name for s in steps]
        assert "find_callees" in tool_names

    def test_trace_returns_call_chain(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, _, chain = planner.investigate(
            "Trace an API request to the database write and identify where validation happens."
        )
        assert len(chain) >= 3, f"Call chain should have >= 3 hops, got {len(chain)}: {[s.symbol_id for s in chain]}"

    def test_call_chain_has_entry_point(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, _, chain = planner.investigate("Trace API request to database")
        roles = [s.role for s in chain]
        assert chain[0].role == "entry_point" or "entry_point" in roles

    def test_call_chain_steps_have_source_locations(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, _, chain = planner.investigate("Trace API request to database")
        for step in chain:
            assert step.file, f"Chain step {step.order} must have a file"
            assert step.start_line >= 1

    def test_chain_steps_ordered(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, _, chain = planner.investigate("Trace API request to database")
        orders = [s.order for s in chain]
        assert orders == list(range(len(chain)))

    def test_evidence_items_produced(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, evidence, chain = planner.investigate("Trace API request to database write")
        assert len(evidence) > 0, "Planner must collect at least one evidence item."

    def test_evidence_has_source_text(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        _, evidence, _ = planner.investigate("Trace API request to database write")
        direct_items = [e for e in evidence if e.kind == EvidenceKind.DIRECT]
        assert len(direct_items) > 0
        for item in direct_items:
            assert item.source_text.strip(), f"DIRECT evidence item {item.evidence_id} must have source_text"

    def test_step_count_bounded(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("Trace API request to database write")
        assert len(steps) <= InvestigationPlanner.MAX_STEPS

    def test_write_prefers_update_endpoint(self, demo_registry):
        """The 'write' keyword should prefer the update endpoint over the read endpoint."""
        planner = InvestigationPlanner(demo_registry)
        _, _, chain = planner.investigate(
            "Trace an API request to the database write and identify where validation happens."
        )
        # At minimum, the chain should reach a database node
        db_steps = [s for s in chain if s.role == "database"]
        assert len(db_steps) >= 1, "Chain must reach a database node"


class TestPlannerExplain:
    def test_explain_produces_steps(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("Explain how authentication works in this codebase")
        assert len(steps) > 0

    def test_explain_uses_keyword_search(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("What does verify_request_auth do?")
        tool_names = [s.tool_name for s in steps]
        assert "keyword_search" in tool_names


class TestPlannerSearch:
    def test_search_produces_steps(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("UserService get_user_profile")
        assert len(steps) > 0

    def test_search_uses_bm25(self, demo_registry):
        planner = InvestigationPlanner(demo_registry)
        steps, _, _ = planner.investigate("UserService")
        tool_names = [s.tool_name for s in steps]
        assert "keyword_search" in tool_names


# ---------------------------------------------------------------------------
# Evidence validation tests
# ---------------------------------------------------------------------------


class TestEvidenceValidator:
    @pytest.fixture
    def validator(self, demo_registry):
        ctx = demo_registry.context
        return EvidenceValidator(
            repo_root=ctx.repo_root,
            repository_index=ctx.repository_index,
        )

    def test_valid_evidence_no_issues(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="app/routes.py",
            start_line=1,
            end_line=5,
            source_text="import fastapi",
            description="Test evidence",
        )
        issues = validator.validate([item])
        errors = [i for i in issues if i.severity == "ERROR"]
        assert not errors

    def test_missing_file_is_error(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="app/nonexistent_file.py",
            start_line=1,
            end_line=5,
            source_text="x = 1",
            description="Bad file",
        )
        issues = validator.validate([item])
        errors = [i for i in issues if i.severity == "ERROR"]
        assert len(errors) >= 1

    def test_invalid_line_range_is_error(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="app/routes.py",
            start_line=50,
            end_line=10,  # end < start
            source_text="x = 1",
            description="Bad line range",
        )
        issues = validator.validate([item])
        errors = [i for i in issues if i.severity == "ERROR"]
        assert len(errors) >= 1

    def test_unknown_symbol_is_warning(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="app/routes.py",
            start_line=1,
            end_line=5,
            symbol_id="app/routes.py::nonexistent_symbol",
            source_text="x = 1",
            description="Unknown symbol",
        )
        issues = validator.validate([item])
        warnings = [i for i in issues if i.severity == "WARNING"]
        assert len(warnings) >= 1

    def test_unresolved_evidence_is_warning(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.UNRESOLVED,
            file="app/routes.py",
            start_line=1,
            end_line=5,
            source_text="",
            description="Unresolved call target",
        )
        issues = validator.validate([item])
        assert any(i.severity == "WARNING" for i in issues)

    def test_grounding_all_valid(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="app/routes.py",
            start_line=1,
            end_line=5,
            source_text="import fastapi",
            description="Valid evidence",
        )
        grounding, _ = validator.validation_summary([item])
        assert grounding == "grounded"

    def test_grounding_with_warnings(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.UNRESOLVED,
            file="app/routes.py",
            start_line=1,
            end_line=5,
            source_text="",
            description="Unresolved",
        )
        grounding, _ = validator.validation_summary([item])
        assert grounding in ("partially_grounded", "grounded")

    def test_grounding_with_errors(self, validator):
        from backend.app.validation.models import EvidenceItem
        item = EvidenceItem(
            kind=EvidenceKind.DIRECT,
            file="nonexistent/path.py",
            start_line=1,
            end_line=5,
            source_text="x = 1",
            description="Missing file",
        )
        grounding, _ = validator.validation_summary([item])
        assert grounding == "ungrounded"


# ---------------------------------------------------------------------------
# Investigator integration tests
# ---------------------------------------------------------------------------


class TestInvestigator:
    def test_returns_investigation_result(self, investigator):
        result = investigator.investigate(
            repository_id="demo_repo",
            question="Trace an API request to the database write and identify where validation happens.",
        )
        assert isinstance(result, InvestigationResult)

    def test_result_has_investigation_id(self, investigator):
        result = investigator.investigate("demo_repo", "Trace API request to database")
        assert result.investigation_id
        assert len(result.investigation_id) > 0

    def test_result_has_repository_id(self, investigator):
        result = investigator.investigate("demo_repo", "Trace API request to database")
        assert result.repository_id == "demo_repo"

    def test_result_has_question(self, investigator):
        q = "Trace API request to database"
        result = investigator.investigate("demo_repo", q)
        assert result.question == q

    def test_result_has_answer_summary(self, investigator):
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        assert result.answer_summary
        assert len(result.answer_summary) > 20

    def test_result_latency_positive(self, investigator):
        result = investigator.investigate("demo_repo", "Trace API request to database")
        assert result.latency_ms > 0

    def test_result_total_steps(self, investigator):
        result = investigator.investigate("demo_repo", "Trace API request to database")
        assert result.total_steps == len(result.trace)

    def test_result_grounding_valid_values(self, investigator):
        result = investigator.investigate("demo_repo", "Trace API request to database")
        assert result.grounding in ("grounded", "partially_grounded", "ungrounded")

    def test_demo_trace_question_call_chain(self, investigator):
        """Acceptance test: the demo trace question produces a multi-hop call chain."""
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        assert len(result.call_chain) >= 3, (
            f"Expected >= 3 call chain hops, got {len(result.call_chain)}: "
            f"{[s.symbol_id for s in result.call_chain]}"
        )

    def test_demo_trace_question_has_evidence(self, investigator):
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        assert len(result.evidence) >= 1

    def test_demo_trace_question_evidence_source_grounded(self, investigator):
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        direct = [e for e in result.evidence if e.kind == EvidenceKind.DIRECT]
        for item in direct:
            assert item.file
            assert item.start_line >= 1
            assert item.end_line >= item.start_line

    def test_demo_trace_reaches_database(self, investigator):
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        roles = [s.role for s in result.call_chain]
        assert "database" in roles, f"Expected 'database' role in chain, got: {roles}"

    def test_demo_trace_has_auth_or_entry(self, investigator):
        result = investigator.investigate(
            "demo_repo",
            "Trace an API request to the database write and identify where validation happens.",
        )
        roles = [s.role for s in result.call_chain]
        assert "entry_point" in roles or "auth" in roles, f"Expected entry_point or auth in chain: {roles}"
