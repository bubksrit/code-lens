"""Tests for structure-aware code chunking (backend.app.retrieval.chunker).

Validates:
- module chunks
- class chunks
- function chunks
- method chunks
- parent symbol relationships
- exact line mappings to original source
- oversized functions with deterministic statement-based splitting
- no source-line loss
- deterministic chunk IDs
- lookup functions (get_chunk, get_chunks_for_symbol)
- demo repository integration
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.app.ingestion.scanner import scan_repository
from backend.app.retrieval.chunker import (
    build_chunks,
    get_chunk,
    get_chunks_for_symbol,
)
from backend.app.retrieval.models import ChunkKind


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

def _create_repo(tmp_path: Path, files: dict[str, str]):
    for rel_path, content in files.items():
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return scan_repository(str(tmp_path))


# ---------------------------------------------------------------------------
# Module Chunks
# ---------------------------------------------------------------------------

class TestModuleChunks:
    def test_module_chunk_created(self, tmp_path: Path):
        code = textwrap.dedent('''\
            """Module docstring."""
            import os
            from typing import List

            def helper():
                return 1
        ''')
        repo_idx = _create_repo(tmp_path, {"test_mod.py": code})
        chunk_idx = build_chunks(repo_idx)

        mod_chunks = chunk_idx.get_chunks_by_kind("module")
        assert len(mod_chunks) == 1
        mc = mod_chunks[0]
        assert mc.kind == "module"
        assert mc.file == "test_mod.py"
        assert mc.chunk_id == "test_mod.py::module"
        assert mc.symbol_id == "test_mod.py::module"
        assert mc.start_line == 1
        assert mc.end_line >= 1
        assert "Module docstring." in mc.context.get("docstring", "")
        imports = mc.context.get("imports", [])
        assert any("os" in imp for imp in imports)
        assert any("typing" in imp for imp in imports)

    def test_module_chunk_empty_file(self, tmp_path: Path):
        repo_idx = _create_repo(tmp_path, {"empty.py": ""})
        chunk_idx = build_chunks(repo_idx)
        mod_chunks = chunk_idx.get_chunks_by_kind("module")
        assert len(mod_chunks) == 1
        assert mod_chunks[0].start_line == 1
        assert mod_chunks[0].end_line == 1
        assert mod_chunks[0].text == ""


# ---------------------------------------------------------------------------
# Class Chunks
# ---------------------------------------------------------------------------

class TestClassChunks:
    def test_class_chunk_created(self, tmp_path: Path):
        code = textwrap.dedent('''\
            class UserService:
                """User business logic."""

                def get_user(self, user_id: str):
                    return {"id": user_id}

                def delete_user(self, user_id: str):
                    return True
        ''')
        repo_idx = _create_repo(tmp_path, {"services.py": code})
        chunk_idx = build_chunks(repo_idx)

        class_chunks = chunk_idx.get_chunks_by_kind("class")
        assert len(class_chunks) == 1
        cc = class_chunks[0]
        assert cc.kind == "class"
        assert cc.symbol == "UserService"
        assert cc.chunk_id == "services.py::UserService"
        assert "class UserService:" in cc.text
        assert cc.context["docstring"] == "User business logic."
        assert "get_user" in cc.context["methods"]
        assert "delete_user" in cc.context["methods"]


# ---------------------------------------------------------------------------
# Function Chunks
# ---------------------------------------------------------------------------

class TestFunctionChunks:
    def test_function_chunk_created(self, tmp_path: Path):
        code = textwrap.dedent('''\
            from app.errors import AppError

            def compute_total(price: float, tax: float) -> float:
                """Calculate total with tax."""
                if price < 0:
                    raise AppError("Negative price")
                return price + tax
        ''')
        repo_idx = _create_repo(tmp_path, {"calc.py": code})
        chunk_idx = build_chunks(repo_idx)

        fn_chunks = chunk_idx.get_chunks_by_kind("function")
        assert len(fn_chunks) == 1
        fc = fn_chunks[0]
        assert fc.kind == "function"
        assert fc.symbol == "compute_total"
        assert fc.chunk_id == "calc.py::compute_total"
        assert fc.symbol_id == "calc.py::compute_total"
        assert "def compute_total" in fc.text
        assert "compute_total" in fc.context["signature"]
        assert fc.context["docstring"] == "Calculate total with tax."
        # Verify relevant import captured
        assert any("AppError" in imp for imp in fc.context["relevant_imports"])


# ---------------------------------------------------------------------------
# Method Chunks & Parent Symbol Relationships
# ---------------------------------------------------------------------------

class TestMethodChunks:
    def test_method_chunk_and_parent_relationship(self, tmp_path: Path):
        code = textwrap.dedent('''\
            class AuthManager:
                def verify_token(self, token: str) -> bool:
                    """Verify token validity."""
                    return len(token) > 5
        ''')
        repo_idx = _create_repo(tmp_path, {"auth.py": code})
        chunk_idx = build_chunks(repo_idx)

        method_chunks = chunk_idx.get_chunks_by_kind("method")
        assert len(method_chunks) == 1
        mc = method_chunks[0]
        assert mc.kind == "method"
        assert mc.symbol == "verify_token"
        assert mc.chunk_id == "auth.py::AuthManager.verify_token"
        assert mc.context["containing_class"] == "AuthManager"
        assert mc.context["docstring"] == "Verify token validity."

        # Verify class chunk exists and lists method
        class_chunks = chunk_idx.get_chunks_by_kind("class")
        assert len(class_chunks) == 1
        assert "verify_token" in class_chunks[0].context["methods"]


# ---------------------------------------------------------------------------
# Exact Line Mappings
# ---------------------------------------------------------------------------

class TestExactLineMappings:
    def test_all_chunks_map_to_source_lines(self, tmp_path: Path):
        code = textwrap.dedent('''\
            import os

            class Helper:
                def run(self):
                    return True

            def standalone():
                x = 1
                y = 2
                return x + y
        ''')
        repo_idx = _create_repo(tmp_path, {"mapped.py": code})
        chunk_idx = build_chunks(repo_idx)
        source_lines = code.splitlines()

        for chunk in chunk_idx.all_chunks():
            assert chunk.start_line <= chunk.end_line
            # Reconstruct exact slice from original source lines
            expected_text = "\n".join(source_lines[chunk.start_line - 1 : chunk.end_line])
            assert chunk.text == expected_text, (
                f"Mismatch for chunk {chunk.chunk_id}: line {chunk.start_line}..{chunk.end_line}"
            )


# ---------------------------------------------------------------------------
# Oversized Functions & Deterministic Splitting
# ---------------------------------------------------------------------------

class TestOversizedFunctions:
    def test_oversized_function_split_without_line_loss(self, tmp_path: Path):
        # Create a function with 30 distinct statements
        lines = ["def huge_function():"]
        lines.append('    """Large function docstring."""')
        for i in range(30):
            lines.append(f"    var_{i} = {i} * 2")
        lines.append("    return var_29")
        code = "\n".join(lines) + "\n"

        repo_idx = _create_repo(tmp_path, {"huge.py": code})
        # Set max_lines to 12 to force multiple parts
        chunk_idx = build_chunks(repo_idx, max_lines_per_chunk=12)

        parts = [c for c in chunk_idx.all_chunks() if c.symbol == "huge_function"]
        assert len(parts) >= 2, f"Expected multiple parts, got {len(parts)}"

        # 1. Preserves symbol_id across parts
        for part in parts:
            assert part.symbol_id == "huge.py::huge_function"
            assert part.kind == "function"
            assert part.context["is_split"] is True

        # 2. Deterministic chunk IDs
        for idx, part in enumerate(parts, start=1):
            assert part.chunk_id == f"huge.py::huge_function::part_{idx}"
            assert part.context["part"] == idx
            assert part.context["total_parts"] == len(parts)

        # 3. No source-line loss & no overlapping lines
        source_lines = code.splitlines()
        first_part = parts[0]
        last_part = parts[-1]
        assert first_part.start_line == 1  # starts at def line
        assert last_part.end_line == len(source_lines)  # ends at last line

        for i in range(len(parts) - 1):
            curr_p = parts[i]
            next_p = parts[i + 1]
            assert next_p.start_line == curr_p.end_line + 1, (
                f"Gap or overlap between part {curr_p.chunk_id} and {next_p.chunk_id}"
            )

        # 4. Every part matches source lines exactly
        for part in parts:
            expected = "\n".join(source_lines[part.start_line - 1 : part.end_line])
            assert part.text == expected


# ---------------------------------------------------------------------------
# Deterministic Chunk IDs & Lookup Functions
# ---------------------------------------------------------------------------

class TestDeterministicChunkIDsAndLookup:
    def test_chunk_ids_are_stable(self, tmp_path: Path):
        code = textwrap.dedent('''\
            class StableClass:
                def action(self):
                    return "ok"

            def stable_func():
                return 42
        ''')
        repo_idx = _create_repo(tmp_path, {"stable.py": code})
        idx1 = build_chunks(repo_idx)
        idx2 = build_chunks(repo_idx)

        ids1 = [c.chunk_id for c in idx1.all_chunks()]
        ids2 = [c.chunk_id for c in idx2.all_chunks()]
        assert ids1 == ids2

    def test_get_chunk_and_get_chunks_for_symbol(self, tmp_path: Path):
        code = textwrap.dedent('''\
            def find_me():
                return True
        ''')
        repo_idx = _create_repo(tmp_path, {"lookup.py": code})
        chunk_idx = build_chunks(repo_idx)

        # Via get_chunk
        chunk = get_chunk("lookup.py::find_me", chunk_idx)
        assert chunk is not None
        assert chunk.symbol == "find_me"

        # Non-existent chunk
        assert get_chunk("lookup.py::no_such_chunk", chunk_idx) is None

        # Via get_chunks_for_symbol
        sym_chunks = get_chunks_for_symbol("lookup.py::find_me", chunk_idx)
        assert len(sym_chunks) == 1
        assert sym_chunks[0].chunk_id == "lookup.py::find_me"


# ---------------------------------------------------------------------------
# Demo Repository Integration Test
# ---------------------------------------------------------------------------

class TestDemoRepoChunkingIntegration:
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    @pytest.fixture(scope="class")
    @classmethod
    def demo_chunks(cls):
        if not cls.DEMO_ROOT.is_dir():
            pytest.skip("data/demo_repo not found")
        repo_idx = scan_repository(str(cls.DEMO_ROOT))
        return repo_idx, build_chunks(repo_idx)

    def test_total_chunks_and_types_present(self, demo_chunks):
        repo_idx, chunk_idx = demo_chunks
        assert len(chunk_idx) > 0

        kinds = {c.kind for c in chunk_idx.all_chunks()}
        assert "module" in kinds
        assert "class" in kinds
        assert "function" in kinds
        assert "method" in kinds

    def test_every_symbol_has_a_chunk(self, demo_chunks):
        repo_idx, chunk_idx = demo_chunks
        for sym in repo_idx.all_symbols():
            chunks = chunk_idx.get_chunks_for_symbol(sym.symbol_id)
            assert len(chunks) >= 1, f"Symbol {sym.symbol_id} has no matching chunk"

    def test_every_chunk_is_source_grounded(self, demo_chunks):
        repo_idx, chunk_idx = demo_chunks
        root_path = Path(repo_idx.root)

        # Cache file lines for verification
        file_lines: dict[str, list[str]] = {}

        for chunk in chunk_idx.all_chunks():
            # 1. References existing file
            abs_file = root_path / chunk.file
            assert abs_file.is_file(), f"Chunk file {chunk.file} does not exist"

            # 2. Valid start and end lines
            assert chunk.start_line >= 1, f"Bad start_line for {chunk.chunk_id}"
            assert chunk.end_line >= chunk.start_line, f"start_line > end_line for {chunk.chunk_id}"

            # 3. Maps back to original source text
            if chunk.file not in file_lines:
                file_lines[chunk.file] = abs_file.read_text(encoding="utf-8").splitlines()
            lines = file_lines[chunk.file]

            expected_text = "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
            assert chunk.text == expected_text, (
                f"Source mismatch for chunk {chunk.chunk_id} in {chunk.file}"
            )

    def test_key_demo_functions_and_classes_have_chunks(self, demo_chunks):
        _, chunk_idx = demo_chunks
        symbols_found = {c.symbol for c in chunk_idx.all_chunks()}

        # Verify key classes
        assert "UserService" in symbols_found
        assert "UserRepository" in symbols_found
        assert "DatabaseConnection" in symbols_found

        # Verify key functions and methods
        assert "get_user_profile_endpoint" in symbols_found
        assert "update_user_status_endpoint" in symbols_found
        assert "verify_request_auth" in symbols_found
        assert "get_user_profile" in symbols_found
        assert "find_by_id" in symbols_found
