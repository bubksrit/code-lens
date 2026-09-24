"""Tests for controlled agent investigation tools (backend.app.agent).

Validates:
- Typed inputs and outputs across all 6 tools
- Successful execution of keyword_search, symbol_lookup, find_callers, find_callees, get_source, get_chunk
- Error handling on missing symbols, missing chunks, invalid input types
- Security enforcement: rejection of path traversal ('..') and absolute paths
- Line-range validation in get_source
- Bounded result counts
- Preservation of evidence metadata
- Independent execution sequence on data/demo_repo
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.app.agent.models import (
    FindCalleesOutput,
    FindCallersOutput,
    GetChunkOutput,
    GetSourceOutput,
    KeywordSearchOutput,
    SymbolLookupOutput,
    ToolResult,
)
from backend.app.agent.tools import create_tool_registry
from backend.app.graph.models import CallResolution


# ---------------------------------------------------------------------------
# Fixture: Synthetic Test Repository
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_registry(tmp_path: Path):
    auth_code = textwrap.dedent("""\
        def verify_token(token: str) -> bool:
            \"\"\"Verify token string.\"\"\"
            return len(token) > 0
    """)
    service_code = textwrap.dedent("""\
        from auth import verify_token

        class UserService:
            \"\"\"User business service.\"\"\"

            def get_user_profile(self, user_id: str) -> dict:
                \"\"\"Retrieve profile for a user.\"\"\"
                if verify_token("token"):
                    return {"id": user_id}
                return {}
    """)
    (tmp_path / "auth.py").write_text(auth_code, encoding="utf-8")
    (tmp_path / "service.py").write_text(service_code, encoding="utf-8")
    return create_tool_registry(tmp_path)


# ---------------------------------------------------------------------------
# Tool 1: keyword_search
# ---------------------------------------------------------------------------

class TestKeywordSearchTool:
    def test_keyword_search_success(self, sample_registry):
        res = sample_registry.keyword_search(query="verify token", top_k=5)
        assert res.success is True
        assert res.tool_name == "keyword_search"
        data: KeywordSearchOutput = res.data
        assert data.total_found >= 1
        top_res = data.results[0]
        assert top_res.file in ("auth.py", "service.py")
        assert top_res.start_line >= 1
        assert top_res.end_line >= top_res.start_line
        assert top_res.rank == 1

    def test_keyword_search_bounded(self, sample_registry):
        res = sample_registry.keyword_search(query="user", top_k=1)
        assert res.success is True
        assert len(res.data.results) <= 1

    def test_keyword_search_empty_query(self, sample_registry):
        res = sample_registry.execute("keyword_search", {"query": "", "top_k": 5})
        assert res.success is False
        assert "validation error" in res.error.lower()


# ---------------------------------------------------------------------------
# Tool 2: symbol_lookup
# ---------------------------------------------------------------------------

class TestSymbolLookupTool:
    def test_lookup_by_exact_symbol_id(self, sample_registry):
        res = sample_registry.symbol_lookup("auth.py::verify_token")
        assert res.success is True
        data: SymbolLookupOutput = res.data
        assert data.total_found == 1
        sym = data.symbols[0]
        assert sym.name == "verify_token"
        assert sym.file == "auth.py"
        assert sym.start_line == 1
        assert "def verify_token" in sym.signature

    def test_lookup_by_simple_name(self, sample_registry):
        res = sample_registry.symbol_lookup("UserService")
        assert res.success is True
        data: SymbolLookupOutput = res.data
        assert data.total_found >= 1
        assert data.symbols[0].name == "UserService"
        assert data.symbols[0].kind == "class"

    def test_lookup_by_qualified_name(self, sample_registry):
        res = sample_registry.symbol_lookup("UserService.get_user_profile")
        assert res.success is True
        data: SymbolLookupOutput = res.data
        assert data.total_found == 1
        assert data.symbols[0].name == "get_user_profile"

    def test_lookup_missing_symbol(self, sample_registry):
        res = sample_registry.symbol_lookup("nonexistent_symbol_xyz")
        assert res.success is False
        assert "was not found" in res.error


# ---------------------------------------------------------------------------
# Tool 3 & 4: find_callers & find_callees
# ---------------------------------------------------------------------------

class TestCallGraphTools:
    def test_find_callees_success(self, sample_registry):
        res = sample_registry.find_callees("service.py::UserService.get_user_profile")
        assert res.success is True
        data: FindCalleesOutput = res.data
        assert data.total_found >= 1
        callee_ids = [c.callee for c in data.callees]
        assert "auth.py::verify_token" in callee_ids
        edge = next(c for c in data.callees if c.callee == "auth.py::verify_token")
        assert edge.resolution == CallResolution.EXACT.value
        assert edge.file == "service.py"
        assert edge.line >= 1

    def test_find_callers_success(self, sample_registry):
        res = sample_registry.find_callers("auth.py::verify_token")
        assert res.success is True
        data: FindCallersOutput = res.data
        assert data.total_found >= 1
        callers = [c.caller for c in data.callers]
        assert "service.py::UserService.get_user_profile" in callers

    def test_find_callers_nonexistent(self, sample_registry):
        res = sample_registry.find_callers("no_such_symbol")
        assert res.success is True
        assert res.data.total_found == 0

    def test_find_callers_bounded(self, sample_registry):
        res = sample_registry.execute(
            "find_callers",
            {"symbol_id": "auth.py::verify_token", "limit": 1},
        )
        assert res.success is True
        assert len(res.data.callers) <= 1


# ---------------------------------------------------------------------------
# Tool 5: get_source & Security Sandbox
# ---------------------------------------------------------------------------

class TestGetSourceTool:
    def test_get_source_success(self, sample_registry):
        res = sample_registry.get_source("auth.py", 1, 3)
        assert res.success is True
        data: GetSourceOutput = res.data
        assert data.file == "auth.py"
        assert data.start_line == 1
        assert data.end_line == 3
        assert "def verify_token" in data.text
        assert data.total_lines == 3

    def test_rejects_path_traversal_dot_dot(self, sample_registry):
        res = sample_registry.get_source("../secret.py", 1, 5)
        assert res.success is False
        assert "path traversal" in res.error.lower() or "not permitted" in res.error.lower()

    def test_rejects_nested_path_traversal(self, sample_registry):
        res = sample_registry.get_source("app/../../etc/passwd", 1, 5)
        assert res.success is False
        assert "path traversal" in res.error.lower() or "not permitted" in res.error.lower()

    def test_rejects_absolute_path(self, sample_registry):
        res = sample_registry.get_source("C:/Windows/win.ini", 1, 5)
        assert res.success is False
        assert "absolute path" in res.error.lower() or "not permitted" in res.error.lower()

    def test_rejects_nonexistent_file(self, sample_registry):
        res = sample_registry.get_source("missing_file.py", 1, 5)
        assert res.success is False
        assert "does not exist" in res.error.lower()

    def test_rejects_invalid_line_range_start_less_than_one(self, sample_registry):
        res = sample_registry.get_source("auth.py", 0, 5)
        assert res.success is False
        assert "line numbers are 1-based" in res.error.lower() or "validation error" in res.error.lower()

    def test_rejects_start_greater_than_end(self, sample_registry):
        res = sample_registry.get_source("auth.py", 5, 2)
        assert res.success is False
        assert "cannot exceed end_line" in res.error.lower()

    def test_rejects_start_exceeding_total_lines(self, sample_registry):
        res = sample_registry.get_source("auth.py", 9999, 10000)
        assert res.success is False
        assert "exceeds total lines" in res.error.lower()


# ---------------------------------------------------------------------------
# Tool 6: get_chunk
# ---------------------------------------------------------------------------

class TestGetChunkTool:
    def test_get_chunk_success(self, sample_registry):
        chunk_id = "auth.py::verify_token"
        res = sample_registry.get_chunk(chunk_id)
        assert res.success is True
        data: GetChunkOutput = res.data
        assert data.chunk.chunk_id == chunk_id
        assert data.chunk.file == "auth.py"
        assert "def verify_token" in data.chunk.text

    def test_get_chunk_missing(self, sample_registry):
        res = sample_registry.get_chunk("nonexistent_chunk_id")
        assert res.success is False
        assert "was not found" in res.error


# ---------------------------------------------------------------------------
# Tool Registry & Schema Definitions
# ---------------------------------------------------------------------------

class TestToolRegistryDefinitions:
    def test_tool_definitions_present_and_valid(self, sample_registry):
        definitions = sample_registry.get_tool_definitions()
        assert len(definitions) == 6
        names = {d.name for d in definitions}
        expected = {
            "keyword_search",
            "symbol_lookup",
            "find_callers",
            "find_callees",
            "get_source",
            "get_chunk",
        }
        assert names == expected
        for d in definitions:
            assert len(d.description) > 10
            assert "properties" in d.parameters

    def test_execute_unknown_tool(self, sample_registry):
        res = sample_registry.execute("arbitrary_shell_exec", {"cmd": "ls"})
        assert res.success is False
        assert "unknown tool" in res.error.lower()


# ---------------------------------------------------------------------------
# Integration Demonstration on data/demo_repo
# ---------------------------------------------------------------------------

class TestDemoRepoAgentInvestigationIntegration:
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    @pytest.fixture(scope="class")
    @classmethod
    def demo_registry(cls):
        if not cls.DEMO_ROOT.is_dir():
            pytest.skip("data/demo_repo not found")
        return create_tool_registry(cls.DEMO_ROOT)

    def test_complete_investigation_workflow(self, demo_registry):
        """Demonstrate the independent investigation sequence required by acceptance criteria:
        1. search for 'get user profile'
        2. look up UserService.get_user_profile
        3. find its callers and callees
        4. retrieve the relevant source range
        5. retrieve the corresponding chunk
        """
        # Step 1: keyword_search
        search_res = demo_registry.keyword_search("get user profile", top_k=5)
        assert search_res.success is True
        search_data: KeywordSearchOutput = search_res.data
        assert search_data.total_found > 0
        symbols_found = [r.symbol for r in search_data.results]
        assert "get_user_profile" in symbols_found or "get_user_profile_endpoint" in symbols_found

        # Step 2: symbol_lookup
        lookup_res = demo_registry.symbol_lookup("UserService.get_user_profile")
        assert lookup_res.success is True
        lookup_data: SymbolLookupOutput = lookup_res.data
        assert lookup_data.total_found == 1
        target_sym = lookup_data.symbols[0]
        assert target_sym.name == "get_user_profile"
        assert target_sym.file == "app/services/users.py"
        assert target_sym.start_line == 14
        assert target_sym.end_line == 28

        # Step 3: find callers and callees
        callers_res = demo_registry.find_callers(target_sym.symbol_id)
        assert callers_res.success is True
        callers_data: FindCallersOutput = callers_res.data
        assert callers_data.total_found >= 1
        caller_ids = [c.caller for c in callers_data.callers]
        assert "app/routes.py::get_user_profile_endpoint" in caller_ids

        callees_res = demo_registry.find_callees(target_sym.symbol_id)
        assert callees_res.success is True
        callees_data: FindCalleesOutput = callees_res.data
        assert callees_data.total_found >= 1
        callee_ids = [c.callee for c in callees_data.callees]
        assert any("find_by_id" in cid for cid in callee_ids)

        # Step 4: retrieve source range
        source_res = demo_registry.get_source(
            file=target_sym.file,
            start_line=target_sym.start_line,
            end_line=target_sym.end_line,
        )
        assert source_res.success is True
        source_data: GetSourceOutput = source_res.data
        assert source_data.file == "app/services/users.py"
        assert "def get_user_profile(self, user_id: str)" in source_data.text
        assert source_data.total_lines == 15

        # Step 5: retrieve chunk
        chunk_res = demo_registry.get_chunk(target_sym.symbol_id)
        assert chunk_res.success is True
        chunk_data: GetChunkOutput = chunk_res.data
        assert chunk_data.chunk.symbol_id == target_sym.symbol_id
        assert chunk_data.chunk.kind == "method"
        assert chunk_data.chunk.context["containing_class"] == "UserService"
        assert chunk_data.chunk.start_line == target_sym.start_line
        assert chunk_data.chunk.end_line == target_sym.end_line
