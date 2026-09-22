"""Tests for static call graph analysis (backend.app.graph).

Validates:
- direct local function calls (exact)
- imported functions and cross-module calls (exact)
- class method calls on self and typed instances
- recursive function calls (exact)
- unresolved dynamic or external calls (unresolved)
- multiple candidate targets (probable)
- caller / callee lookup
- short call-path traversal
- integration with demo repository main call chain
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.app.graph.call_graph import (
    build_call_graph,
    find_callees,
    find_callers,
    find_path,
)
from backend.app.graph.models import CallResolution
from backend.app.ingestion.scanner import scan_repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_repo(tmp_path: Path, files: dict[str, str]):
    for rel_path, content in files.items():
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return scan_repository(str(tmp_path))


# ---------------------------------------------------------------------------
# Direct Function Call Tests
# ---------------------------------------------------------------------------

class TestDirectFunctionCall:
    def test_local_direct_call_is_exact(self, tmp_path: Path):
        code = textwrap.dedent("""\
            def helper():
                return 1

            def main():
                val = helper()
                return val
        """)
        repo_idx = _create_repo(tmp_path, {"app.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("app.py::main")
        assert len(callees) >= 1
        edge = next(e for e in callees if e.callee == "app.py::helper")
        assert edge.caller == "app.py::main"
        assert edge.resolution == CallResolution.EXACT.value
        assert edge.line == 5
        assert "helper()" in edge.call_expr


# ---------------------------------------------------------------------------
# Imported Function Tests
# ---------------------------------------------------------------------------

class TestImportedFunction:
    def test_imported_function_call_is_exact(self, tmp_path: Path):
        lib_code = textwrap.dedent("""\
            def authenticate(token: str) -> bool:
                return token == "secret"
        """)
        app_code = textwrap.dedent("""\
            from lib import authenticate

            def login():
                return authenticate("secret")
        """)
        repo_idx = _create_repo(tmp_path, {"lib.py": lib_code, "app.py": app_code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("app.py::login")
        assert len(callees) >= 1
        edge = next(e for e in callees if e.callee == "lib.py::authenticate")
        assert edge.resolution == CallResolution.EXACT.value
        assert edge.file == "app.py"


# ---------------------------------------------------------------------------
# Class Method Tests
# ---------------------------------------------------------------------------

class TestClassMethod:
    def test_self_method_call_is_exact(self, tmp_path: Path):
        code = textwrap.dedent("""\
            class Validator:
                def validate(self, val: str) -> bool:
                    return self._check(val)

                def _check(self, val: str) -> bool:
                    return len(val) > 0
        """)
        repo_idx = _create_repo(tmp_path, {"val.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("val.py::Validator.validate")
        assert len(callees) >= 1
        edge = next(e for e in callees if e.callee == "val.py::Validator._check")
        assert edge.resolution == CallResolution.EXACT.value

    def test_instantiated_object_method_call(self, tmp_path: Path):
        code = textwrap.dedent("""\
            class Engine:
                def start(self):
                    return True

            def boot():
                engine = Engine()
                return engine.start()
        """)
        repo_idx = _create_repo(tmp_path, {"boot.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("boot.py::boot")
        edge = next(e for e in callees if e.callee == "boot.py::Engine.start")
        assert edge.resolution == CallResolution.EXACT.value


# ---------------------------------------------------------------------------
# Recursion Tests
# ---------------------------------------------------------------------------

class TestRecursion:
    def test_recursive_call_is_exact(self, tmp_path: Path):
        code = textwrap.dedent("""\
            def factorial(n: int) -> int:
                if n <= 1:
                    return 1
                return n * factorial(n - 1)
        """)
        repo_idx = _create_repo(tmp_path, {"math_ops.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("math_ops.py::factorial")
        self_edge = next(e for e in callees if e.callee == "math_ops.py::factorial")
        assert self_edge.caller == "math_ops.py::factorial"
        assert self_edge.resolution == CallResolution.EXACT.value


# ---------------------------------------------------------------------------
# Unresolved Call Tests
# ---------------------------------------------------------------------------

class TestUnresolvedCall:
    def test_external_or_dynamic_call_is_unresolved(self, tmp_path: Path):
        code = textwrap.dedent("""\
            def execute_dynamic(handler):
                return handler()
        """)
        repo_idx = _create_repo(tmp_path, {"dyn.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("dyn.py::execute_dynamic")
        assert len(callees) == 1
        edge = callees[0]
        assert edge.resolution == CallResolution.UNRESOLVED.value
        assert edge.callee == "handler"


# ---------------------------------------------------------------------------
# Multiple Possible Targets Tests
# ---------------------------------------------------------------------------

class TestMultiplePossibleTargets:
    def test_ambiguous_method_call_marks_probable_candidates(self, tmp_path: Path):
        code = textwrap.dedent("""\
            class FileStore:
                def save(self, data):
                    return True

            class DbStore:
                def save(self, data):
                    return True

            def persist(store, data):
                return store.save(data)
        """)
        repo_idx = _create_repo(tmp_path, {"stores.py": code})
        graph = build_call_graph(repo_idx)

        callees = graph.find_callees("stores.py::persist")
        save_callees = [e for e in callees if "save" in e.callee]
        assert len(save_callees) == 2
        for edge in save_callees:
            assert edge.resolution == CallResolution.PROBABLE.value
        targets = {e.callee for e in save_callees}
        assert "stores.py::FileStore.save" in targets
        assert "stores.py::DbStore.save" in targets


# ---------------------------------------------------------------------------
# Short Call-Path Traversal Tests
# ---------------------------------------------------------------------------

class TestCallPathTraversal:
    def test_three_hop_path_found(self, tmp_path: Path):
        code = textwrap.dedent("""\
            def step_c():
                return "done"

            def step_b():
                return step_c()

            def step_a():
                return step_b()
        """)
        repo_idx = _create_repo(tmp_path, {"flow.py": code})
        graph = build_call_graph(repo_idx)

        path = graph.find_path("flow.py::step_a", "flow.py::step_c")
        assert path is not None
        assert len(path) == 2
        assert path[0].caller == "flow.py::step_a"
        assert path[0].callee == "flow.py::step_b"
        assert path[1].caller == "flow.py::step_b"
        assert path[1].callee == "flow.py::step_c"

    def test_nonexistent_path_returns_none(self, tmp_path: Path):
        code = textwrap.dedent("""\
            def isolated_x():
                return 1

            def isolated_y():
                return 2
        """)
        repo_idx = _create_repo(tmp_path, {"iso.py": code})
        graph = build_call_graph(repo_idx)

        assert graph.find_path("iso.py::isolated_x", "iso.py::isolated_y") is None


# ---------------------------------------------------------------------------
# Demo Repository Call Chain Integration Test
# ---------------------------------------------------------------------------

class TestDemoRepoCallChainIntegration:
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    @pytest.fixture(scope="class")
    @classmethod
    def demo_graph(cls):
        if not cls.DEMO_ROOT.is_dir():
            pytest.skip("data/demo_repo not found")
        repo_idx = scan_repository(str(cls.DEMO_ROOT))
        return repo_idx, build_call_graph(repo_idx)

    def test_graph_has_edges_and_resolution_types(self, demo_graph):
        _, graph = demo_graph
        assert len(graph) > 0
        resolutions = {e.resolution for e in graph}
        assert CallResolution.EXACT.value in resolutions
        assert CallResolution.PROBABLE.value in resolutions

    def test_route_calls_auth_and_service(self, demo_graph):
        _, graph = demo_graph
        callees = graph.find_callees("app/routes.py::get_user_profile_endpoint")
        callee_ids = {e.callee for e in callees}

        assert "app/auth.py::verify_request_auth" in callee_ids
        assert "app/services/users.py::UserService.get_user_profile" in callee_ids

    def test_service_calls_repository(self, demo_graph):
        _, graph = demo_graph
        callees = graph.find_callees("app/services/users.py::UserService.get_user_profile")
        callee_ids = {e.callee for e in callees}

        assert "app/repositories/users.py::UserRepository.find_by_id" in callee_ids

    def test_repository_calls_database(self, demo_graph):
        _, graph = demo_graph
        callees = graph.find_callees("app/repositories/users.py::UserRepository.find_by_id")
        callee_ids = {e.callee for e in callees}

        assert any("execute_query" in c for c in callee_ids)

    def test_traverse_main_call_chain(self, demo_graph):
        _, graph = demo_graph
        source = "app/routes.py::get_user_profile_endpoint"
        target = "app/database.py::DatabaseConnection.execute_query"

        path = graph.find_path(source, target)
        assert path is not None, f"Failed to traverse call chain from {source} to {target}"
        assert len(path) >= 3, f"Expected multi-hop call chain, got length {len(path)}"

        # Verify exact chain of callers and callees
        for i in range(len(path) - 1):
            assert path[i].callee == path[i + 1].caller

        # Verify start and end
        assert path[0].caller == source
        assert path[-1].callee == target

    def test_lookup_helpers(self, demo_graph):
        _, graph = demo_graph
        callers = find_callers("app/auth.py::verify_request_auth", graph)
        assert len(callers) >= 2
        caller_ids = {e.caller for e in callers}
        assert "app/routes.py::get_user_profile_endpoint" in caller_ids
        assert "app/routes.py::update_user_status_endpoint" in caller_ids

        callees = find_callees("app/routes.py::update_user_status_endpoint", graph)
        assert len(callees) >= 2
