"""Tests for backend.app.ingestion.python_parser and backend.app.ingestion.scanner.

Every test uses real AST-derived line numbers sourced from the inline source
strings; no expected line numbers are guessed.  We compute them by parsing
the same strings with ast.parse so the tests remain self-consistent.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import List

import pytest

from backend.app.ingestion.models import SymbolKind
from backend.app.ingestion.python_parser import extract_symbols
from backend.app.ingestion.scanner import (
    find_symbol,
    find_symbols_by_file,
    find_symbols_by_name,
    scan_repository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_line(source: str, name: str) -> int:
    """Return the lineno of the first def/class node named *name*."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return node.lineno
    raise ValueError(f"Node {name!r} not found in source")


def _end_line(source: str, name: str) -> int:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return node.end_lineno
    raise ValueError(f"Node {name!r} not found in source")


# ---------------------------------------------------------------------------
# Normal function
# ---------------------------------------------------------------------------

class TestNormalFunction:
    SOURCE = textwrap.dedent("""\
        def add(a: int, b: int) -> int:
            return a + b
    """)

    def test_finds_one_symbol(self):
        idx = extract_symbols(self.SOURCE, "math.py")
        assert len(idx.symbols) == 1

    def test_kind_is_function(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.kind == SymbolKind.FUNCTION

    def test_name_and_qualified_name(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.name == "add"
        assert sym.qualified_name == "add"

    def test_file_stored_correctly(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.file == "math.py"

    def test_symbol_id_format(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.symbol_id == "math.py::add"

    def test_start_line_matches_ast(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.start_line == _first_line(self.SOURCE, "add")

    def test_end_line_matches_ast(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.end_line == _end_line(self.SOURCE, "add")

    def test_no_parent(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.parent_symbol is None

    def test_is_not_async(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert sym.is_async is False

    def test_signature_contains_def(self):
        sym = extract_symbols(self.SOURCE, "math.py").symbols[0]
        assert "def add" in sym.signature


# ---------------------------------------------------------------------------
# Function with docstring
# ---------------------------------------------------------------------------

class TestFunctionDocstring:
    SOURCE = textwrap.dedent("""\
        def greet(name: str) -> str:
            \"\"\"Return a greeting for name.\"\"\"
            return f"Hello, {name}"
    """)

    def test_docstring_extracted(self):
        sym = extract_symbols(self.SOURCE, "greet.py").symbols[0]
        assert sym.docstring == "Return a greeting for name."


# ---------------------------------------------------------------------------
# Class with methods
# ---------------------------------------------------------------------------

class TestClass:
    SOURCE = textwrap.dedent("""\
        class Calculator:
            \"\"\"A simple arithmetic calculator.\"\"\"

            def add(self, a: int, b: int) -> int:
                return a + b

            def subtract(self, a: int, b: int) -> int:
                return a - b
    """)

    def test_three_symbols_extracted(self):
        # class + 2 methods
        idx = extract_symbols(self.SOURCE, "calc.py")
        assert len(idx.symbols) == 3

    def test_class_kind(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        classes = [s for s in idx.symbols if s.kind == SymbolKind.CLASS]
        assert len(classes) == 1
        assert classes[0].name == "Calculator"

    def test_class_docstring(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        cls = next(s for s in idx.symbols if s.kind == SymbolKind.CLASS)
        assert cls.docstring == "A simple arithmetic calculator."

    def test_method_kinds(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        methods = [s for s in idx.symbols if s.kind == SymbolKind.METHOD]
        assert len(methods) == 2

    def test_method_qualified_names(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        qnames = {s.qualified_name for s in idx.symbols if s.kind == SymbolKind.METHOD}
        assert qnames == {"Calculator.add", "Calculator.subtract"}

    def test_method_parent_is_class(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        cls = next(s for s in idx.symbols if s.kind == SymbolKind.CLASS)
        methods = [s for s in idx.symbols if s.kind == SymbolKind.METHOD]
        for m in methods:
            assert m.parent_symbol == cls.symbol_id

    def test_class_start_line_matches_ast(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        cls = next(s for s in idx.symbols if s.kind == SymbolKind.CLASS)
        assert cls.start_line == _first_line(self.SOURCE, "Calculator")

    def test_method_start_line_matches_ast(self):
        idx = extract_symbols(self.SOURCE, "calc.py")
        add = next(s for s in idx.symbols if s.name == "add")
        assert add.start_line == _first_line(self.SOURCE, "add")


# ---------------------------------------------------------------------------
# Async functions and async methods
# ---------------------------------------------------------------------------

class TestAsyncFunctions:
    SOURCE = textwrap.dedent("""\
        async def fetch_user(user_id: str) -> dict:
            \"\"\"Fetch a user from the database.\"\"\"
            return {}

        class UserClient:
            async def get(self, user_id: str) -> dict:
                return {}
    """)

    def test_top_level_async_kind(self):
        idx = extract_symbols(self.SOURCE, "async_mod.py")
        sym = next(s for s in idx.symbols if s.name == "fetch_user")
        assert sym.kind == SymbolKind.ASYNC_FUNCTION

    def test_async_method_kind(self):
        idx = extract_symbols(self.SOURCE, "async_mod.py")
        sym = next(s for s in idx.symbols if s.name == "get")
        assert sym.kind == SymbolKind.ASYNC_METHOD

    def test_is_async_flag_set(self):
        idx = extract_symbols(self.SOURCE, "async_mod.py")
        for sym in idx.symbols:
            if sym.name in ("fetch_user", "get"):
                assert sym.is_async is True

    def test_class_is_not_async(self):
        idx = extract_symbols(self.SOURCE, "async_mod.py")
        cls = next(s for s in idx.symbols if s.kind == SymbolKind.CLASS)
        assert cls.is_async is False

    def test_start_line_matches_ast(self):
        idx = extract_symbols(self.SOURCE, "async_mod.py")
        sym = next(s for s in idx.symbols if s.name == "fetch_user")
        assert sym.start_line == _first_line(self.SOURCE, "fetch_user")


# ---------------------------------------------------------------------------
# Nested functions
# ---------------------------------------------------------------------------

class TestNestedFunctions:
    SOURCE = textwrap.dedent("""\
        def outer():
            def inner():
                return 42
            return inner
    """)

    def test_both_symbols_found(self):
        idx = extract_symbols(self.SOURCE, "nested.py")
        names = {s.name for s in idx.symbols}
        assert names == {"outer", "inner"}

    def test_inner_qualified_name(self):
        idx = extract_symbols(self.SOURCE, "nested.py")
        inner = next(s for s in idx.symbols if s.name == "inner")
        assert inner.qualified_name == "outer.inner"

    def test_inner_parent_is_outer(self):
        idx = extract_symbols(self.SOURCE, "nested.py")
        outer = next(s for s in idx.symbols if s.name == "outer")
        inner = next(s for s in idx.symbols if s.name == "inner")
        assert inner.parent_symbol == outer.symbol_id

    def test_inner_start_line_matches_ast(self):
        idx = extract_symbols(self.SOURCE, "nested.py")
        inner = next(s for s in idx.symbols if s.name == "inner")
        assert inner.start_line == _first_line(self.SOURCE, "inner")


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

class TestDecorators:
    SOURCE = textwrap.dedent("""\
        import functools

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper

        @decorator
        def my_function():
            pass
    """)

    def test_decorator_captured(self):
        idx = extract_symbols(self.SOURCE, "dec.py")
        fn = next(s for s in idx.symbols if s.name == "my_function")
        assert "decorator" in fn.decorators

    def test_wrapper_has_decorator(self):
        idx = extract_symbols(self.SOURCE, "dec.py")
        wrapper = next(s for s in idx.symbols if s.name == "wrapper")
        assert any("wraps" in d for d in wrapper.decorators)

    def test_plain_function_has_empty_decorators(self):
        idx = extract_symbols(self.SOURCE, "dec.py")
        dec_fn = next(s for s in idx.symbols if s.name == "decorator")
        assert dec_fn.decorators == []


# ---------------------------------------------------------------------------
# Syntax errors
# ---------------------------------------------------------------------------

class TestSyntaxError:
    SOURCE = "def broken(\n    pass"

    def test_returns_module_index(self):
        idx = extract_symbols(self.SOURCE, "broken.py")
        assert idx.file == "broken.py"

    def test_no_symbols(self):
        idx = extract_symbols(self.SOURCE, "broken.py")
        assert idx.symbols == []

    def test_diagnostic_recorded(self):
        idx = extract_symbols(self.SOURCE, "broken.py")
        assert len(idx.diagnostics) == 1

    def test_diagnostic_has_file(self):
        idx = extract_symbols(self.SOURCE, "broken.py")
        assert idx.diagnostics[0].file == "broken.py"

    def test_diagnostic_has_message(self):
        idx = extract_symbols(self.SOURCE, "broken.py")
        assert idx.diagnostics[0].message  # non-empty


# ---------------------------------------------------------------------------
# Unicode source
# ---------------------------------------------------------------------------

class TestUnicodeSource:
    SOURCE = textwrap.dedent("""\
        # -*- coding: utf-8 -*-
        def grüßen(name: str) -> str:
            \"\"\"Grüß Gott, Welt!\"\"\"
            return f"Hallo {name}"
    """)

    def test_unicode_name_extracted(self):
        idx = extract_symbols(self.SOURCE, "unicode_mod.py")
        assert len(idx.symbols) == 1
        assert idx.symbols[0].name == "grüßen"

    def test_docstring_unicode(self):
        idx = extract_symbols(self.SOURCE, "unicode_mod.py")
        assert "Grüß Gott" in idx.symbols[0].docstring


# ---------------------------------------------------------------------------
# Empty files
# ---------------------------------------------------------------------------

class TestEmptyFile:
    def test_empty_string(self):
        idx = extract_symbols("", "empty.py")
        assert idx.symbols == []
        assert idx.diagnostics == []

    def test_comments_only(self):
        idx = extract_symbols("# Just a comment\n", "comments.py")
        assert idx.symbols == []

    def test_module_docstring_only(self):
        source = '"""Module with only a docstring."""\n'
        idx = extract_symbols(source, "doconly.py")
        assert idx.symbols == []
        assert idx.module_docstring == "Module with only a docstring."


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

class TestImports:
    SOURCE = textwrap.dedent("""\
        import os
        import sys as system
        from pathlib import Path
        from typing import Dict, Optional

        def main():
            pass
    """)

    def test_plain_import_captured(self):
        idx = extract_symbols(self.SOURCE, "imp.py")
        names = {i.name for i in idx.imports}
        assert "os" in names

    def test_aliased_import_captured(self):
        idx = extract_symbols(self.SOURCE, "imp.py")
        aliased = next(i for i in idx.imports if i.name == "sys")
        assert aliased.alias == "system"

    def test_from_import_module(self):
        idx = extract_symbols(self.SOURCE, "imp.py")
        path_imp = next(i for i in idx.imports if i.name == "Path")
        assert path_imp.module == "pathlib"

    def test_multiple_from_import_names(self):
        idx = extract_symbols(self.SOURCE, "imp.py")
        typing_names = {i.name for i in idx.imports if i.module == "typing"}
        assert typing_names == {"Dict", "Optional"}


# ---------------------------------------------------------------------------
# Source location validity invariants
# ---------------------------------------------------------------------------

class TestLocationInvariants:
    SOURCE = textwrap.dedent("""\
        class Outer:
            def method_a(self):
                pass

            class Inner:
                def method_b(self):
                    pass

        def standalone():
            pass
    """)

    def test_start_le_end_for_all_symbols(self):
        idx = extract_symbols(self.SOURCE, "locations.py")
        for sym in idx.symbols:
            assert sym.start_line <= sym.end_line, (
                f"{sym.qualified_name}: start_line={sym.start_line} > end_line={sym.end_line}"
            )

    def test_start_column_non_negative(self):
        idx = extract_symbols(self.SOURCE, "locations.py")
        for sym in idx.symbols:
            assert sym.start_column >= 0

    def test_end_column_non_negative(self):
        idx = extract_symbols(self.SOURCE, "locations.py")
        for sym in idx.symbols:
            assert sym.end_column >= 0

    def test_all_symbol_ids_unique(self):
        idx = extract_symbols(self.SOURCE, "locations.py")
        ids = [s.symbol_id for s in idx.symbols]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Scanner – file discovery and exclusions
# ---------------------------------------------------------------------------

class TestScanner:
    def test_scan_returns_repository_index(self, tmp_path: Path):
        (tmp_path / "hello.py").write_text("def hello(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        assert idx.root == str(tmp_path)

    def test_symbols_discovered(self, tmp_path: Path):
        (tmp_path / "hello.py").write_text("def hello(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        assert len(idx.all_symbols()) == 1

    def test_pycache_excluded(self, tmp_path: Path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("def cached(): pass\n", encoding="utf-8")
        (tmp_path / "real.py").write_text("def real(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        files = {m.file for m in idx.modules}
        assert not any("__pycache__" in f for f in files)
        assert any("real.py" in f for f in files)

    def test_venv_excluded(self, tmp_path: Path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "site.py").write_text("def venv_fn(): pass\n", encoding="utf-8")
        (tmp_path / "app.py").write_text("def app_fn(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        names = {s.name for s in idx.all_symbols()}
        assert "venv_fn" not in names
        assert "app_fn" in names

    def test_git_dir_excluded(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hooks = git_dir / "hooks"
        hooks.mkdir()
        (hooks / "pre_commit.py").write_text("def hook(): pass\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        names = {s.name for s in idx.all_symbols()}
        assert "hook" not in names

    def test_syntax_error_recorded_as_diagnostic(self, tmp_path: Path):
        (tmp_path / "broken.py").write_text("def broken(\n    pass", encoding="utf-8")
        (tmp_path / "good.py").write_text("def good(): pass\n", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        all_diags = [d for m in idx.modules for d in m.diagnostics]
        assert any("broken.py" in d.file for d in all_diags)
        # good.py still contributes symbols despite broken.py failing
        names = {s.name for s in idx.all_symbols()}
        assert "good" in names

    def test_empty_file_does_not_crash(self, tmp_path: Path):
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        idx = scan_repository(str(tmp_path))
        assert any(m.file == "empty.py" for m in idx.modules)

    def test_deterministic_ordering(self, tmp_path: Path):
        for name in ("zebra.py", "alpha.py", "middle.py"):
            (tmp_path / name).write_text(f"def fn_{name[:3]}(): pass\n", encoding="utf-8")
        idx1 = scan_repository(str(tmp_path))
        idx2 = scan_repository(str(tmp_path))
        assert [m.file for m in idx1.modules] == [m.file for m in idx2.modules]

    def test_invalid_root_raises(self):
        with pytest.raises(ValueError, match="does not exist"):
            scan_repository("/definitely/does/not/exist/xyz")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

class TestLookupHelpers:
    SOURCE_A = textwrap.dedent("""\
        class Service:
            def execute(self):
                pass
    """)
    SOURCE_B = textwrap.dedent("""\
        def execute():
            pass
    """)

    def _build_index(self, tmp_path: Path):
        (tmp_path / "a.py").write_text(self.SOURCE_A, encoding="utf-8")
        (tmp_path / "b.py").write_text(self.SOURCE_B, encoding="utf-8")
        return scan_repository(str(tmp_path))

    def test_find_symbol_by_id(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        sym = find_symbol(idx, "a.py::Service")
        assert sym is not None
        assert sym.name == "Service"

    def test_find_symbol_missing_returns_none(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        assert find_symbol(idx, "nonexistent.py::NoSuchSymbol") is None

    def test_find_symbols_by_name_across_files(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        results = find_symbols_by_name(idx, "execute")
        assert len(results) == 2

    def test_find_symbols_by_name_returns_empty_for_unknown(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        assert find_symbols_by_name(idx, "totally_unknown") == []

    def test_find_symbols_by_file(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        results = find_symbols_by_file(idx, "a.py")
        assert all(s.file == "a.py" for s in results)
        names = {s.name for s in results}
        assert "Service" in names
        assert "execute" in names

    def test_find_symbols_by_file_empty_for_unknown(self, tmp_path: Path):
        idx = self._build_index(tmp_path)
        assert find_symbols_by_file(idx, "nonexistent.py") == []


# ---------------------------------------------------------------------------
# Demo repository integration test
# ---------------------------------------------------------------------------

class TestDemoRepository:
    """Verify the demo repo produces a useful, well-formed symbol index."""

    # backend/tests/ -> backend/ -> samsungprism/ (repo root)
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    @pytest.fixture(scope="class")
    @classmethod
    def demo_index(cls):
        if not cls.DEMO_ROOT.is_dir():
            pytest.skip("data/demo_repo not found")
        return scan_repository(str(cls.DEMO_ROOT))

    def test_symbols_found(self, demo_index):
        assert len(demo_index.all_symbols()) > 0

    def test_no_repo_level_diagnostics(self, demo_index):
        assert demo_index.diagnostics == []

    def test_classes_extracted(self, demo_index):
        classes = [s for s in demo_index.all_symbols() if s.kind == SymbolKind.CLASS]
        assert len(classes) >= 1

    def test_methods_have_class_parents(self, demo_index):
        all_ids = {s.symbol_id for s in demo_index.all_symbols()}
        methods = [s for s in demo_index.all_symbols() if s.kind == SymbolKind.METHOD]
        for m in methods:
            assert m.parent_symbol in all_ids, (
                f"Method {m.symbol_id} has unknown parent {m.parent_symbol}"
            )

    def test_user_service_found(self, demo_index):
        results = find_symbols_by_name(demo_index, "UserService")
        assert len(results) >= 1

    def test_user_repository_found(self, demo_index):
        results = find_symbols_by_name(demo_index, "UserRepository")
        assert len(results) >= 1

    def test_routes_file_indexed(self, demo_index):
        route_syms = find_symbols_by_file(demo_index, "app/routes.py")
        assert len(route_syms) >= 1

    def test_auth_functions_indexed(self, demo_index):
        results = find_symbols_by_name(demo_index, "verify_request_auth")
        assert len(results) >= 1

    def test_all_locations_valid(self, demo_index):
        for sym in demo_index.all_symbols():
            assert sym.start_line >= 1, f"Bad start_line for {sym.symbol_id}"
            assert sym.end_line >= sym.start_line, f"Bad end_line for {sym.symbol_id}"
            assert sym.start_column >= 0
            assert sym.end_column >= 0

    def test_all_symbol_ids_unique_across_repo(self, demo_index):
        ids = [s.symbol_id for s in demo_index.all_symbols()]
        assert len(ids) == len(set(ids)), "Duplicate symbol_ids detected"

    def test_expected_behavior_not_indexed(self, demo_index):
        files = {m.file for m in demo_index.modules}
        assert "EXPECTED_BEHAVIOR.md" not in files
