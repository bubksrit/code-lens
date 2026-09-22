"""Tests for code-aware tokenization and deterministic BM25 lexical retrieval.

Validates:
- tokenization (snake_case, camelCase, PascalCase, dotted paths, import paths)
- exact function and class names
- natural language and partial identifiers
- ranking and edge cases (empty query, empty index, top_k, duplicates)
- save/load persistence and metadata preservation
- integration queries against data/demo_repo
- source grounding of all retrieved results
- benchmark metrics (document count, index time, query latency)
"""
from __future__ import annotations

import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from backend.app.ingestion.scanner import scan_repository
from backend.app.retrieval.bm25 import (
    BM25Index,
    KeywordSearchResult,
    keyword_search,
)
from backend.app.retrieval.chunker import build_chunks
from backend.app.retrieval.models import CodeChunk
from backend.app.retrieval.tokenizer import tokenize_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_sample_chunks() -> list[CodeChunk]:
    return [
        CodeChunk(
            chunk_id="app/calc.py::compute_total",
            file="app/calc.py",
            symbol_id="app/calc.py::compute_total",
            symbol="compute_total",
            kind="function",
            start_line=1,
            end_line=5,
            text="def compute_total(price: float, tax: float) -> float:\n    \"\"\"Calculate total with tax.\"\"\"\n    return price + tax",
            context={
                "module": "app.calc",
                "signature": "def compute_total(price: float, tax: float) -> float:",
                "docstring": "Calculate total with tax.",
                "relevant_imports": ["from app.errors import AppError"],
            },
        ),
        CodeChunk(
            chunk_id="app/auth.py::AuthManager",
            file="app/auth.py",
            symbol_id="app/auth.py::AuthManager",
            symbol="AuthManager",
            kind="class",
            start_line=1,
            end_line=10,
            text="class AuthManager:\n    \"\"\"Handles user authentication and token checks.\"\"\"\n    def verify_token(self, token: str) -> bool:\n        return True",
            context={
                "module": "app.auth",
                "signature": "class AuthManager:",
                "docstring": "Handles user authentication and token checks.",
                "methods": ["verify_token"],
                "relevant_imports": [],
            },
        ),
        CodeChunk(
            chunk_id="app/users.py::get_user_profile",
            file="app/users.py",
            symbol_id="app/users.py::get_user_profile",
            symbol="get_user_profile",
            kind="function",
            start_line=1,
            end_line=6,
            text="def get_user_profile(user_id: str) -> dict:\n    \"\"\"Fetch user profile by id.\"\"\"\n    return {'user_id': user_id}",
            context={
                "module": "app.users",
                "signature": "def get_user_profile(user_id: str) -> dict:",
                "docstring": "Fetch user profile by id.",
                "relevant_imports": [],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tokenizer Tests
# ---------------------------------------------------------------------------

class TestTokenizer:
    def test_snake_case_tokenization(self):
        tokens = tokenize_code("get_user_profile")
        assert "get_user_profile" in tokens
        assert "get" in tokens
        assert "user" in tokens
        assert "profile" in tokens

    def test_camel_case_tokenization(self):
        tokens = tokenize_code("getUserProfile")
        assert "getuserprofile" in tokens
        assert "get" in tokens
        assert "user" in tokens
        assert "profile" in tokens

    def test_pascal_case_tokenization(self):
        tokens = tokenize_code("UserRepository")
        assert "userrepository" in tokens
        assert "user" in tokens
        assert "repository" in tokens

    def test_dotted_identifier_tokenization(self):
        tokens = tokenize_code("UserRepository.find_by_id")
        assert "userrepository.find_by_id" in tokens
        assert "userrepository" in tokens
        assert "find_by_id" in tokens
        assert "find" in tokens
        assert "by" in tokens
        assert "id" in tokens

    def test_import_path_tokenization(self):
        tokens = tokenize_code("app.services.users")
        assert "app.services.users" in tokens
        assert "app" in tokens
        assert "services" in tokens
        assert "users" in tokens

    def test_preserves_original_identifier(self):
        tokens = tokenize_code("validate_jwt_token_header")
        assert "validate_jwt_token_header" in tokens
        assert "jwt" in tokens
        assert "token" in tokens

    def test_empty_string(self):
        assert tokenize_code("") == []
        assert tokenize_code("   ") == []


# ---------------------------------------------------------------------------
# BM25 Edge Cases
# ---------------------------------------------------------------------------

class TestBM25EdgeCases:
    def test_empty_query(self):
        index = BM25Index().build(_create_sample_chunks())
        assert index.search("") == []
        assert index.search("   ") == []

    def test_empty_index(self):
        index = BM25Index().build([])
        assert len(index) == 0
        assert index.search("user") == []

    def test_unknown_terms(self):
        index = BM25Index().build(_create_sample_chunks())
        assert index.search("nonexistentterm_xyz_123") == []

    def test_top_k_larger_than_results(self):
        index = BM25Index().build(_create_sample_chunks())
        results = index.search("user", top_k=50)
        assert len(results) <= len(index)
        assert len(results) > 0

    def test_duplicate_documents_deduplicated(self):
        chunks = _create_sample_chunks()
        # Add duplicate
        chunks_with_dup = chunks + [chunks[0]]
        index = BM25Index().build(chunks_with_dup)
        assert len(index) == len(chunks)


# ---------------------------------------------------------------------------
# BM25 Search Capabilities
# ---------------------------------------------------------------------------

class TestBM25SearchCapabilities:
    @pytest.fixture(autouse=True)
    def setup_index(self):
        self.chunks = _create_sample_chunks()
        self.index = BM25Index().build(self.chunks)

    def test_exact_function_name(self):
        results = self.index.search("compute_total")
        assert len(results) >= 1
        assert results[0].symbol == "compute_total"
        assert results[0].rank == 1

    def test_exact_class_name(self):
        results = self.index.search("AuthManager")
        assert len(results) >= 1
        assert results[0].symbol == "AuthManager"
        assert results[0].rank == 1

    def test_snake_case_query(self):
        results = self.index.search("get_user_profile")
        assert len(results) >= 1
        assert results[0].symbol == "get_user_profile"

    def test_camel_case_query(self):
        results = self.index.search("getUserProfile")
        assert len(results) >= 1
        assert results[0].symbol == "get_user_profile"

    def test_partial_identifier(self):
        results = self.index.search("total")
        assert len(results) >= 1
        assert results[0].symbol == "compute_total"

    def test_natural_language_query(self):
        results = self.index.search("calculate total with tax")
        assert len(results) >= 1
        assert results[0].symbol == "compute_total"

    def test_import_path_query(self):
        results = self.index.search("app.errors")
        assert len(results) >= 1
        assert "app.calc" in results[0].context.get("module", "")

    def test_ranking_relevance(self):
        results = self.index.search("user profile", top_k=5)
        # get_user_profile matches both 'user' and 'profile'
        assert results[0].symbol == "get_user_profile"
        assert results[0].rank == 1
        assert results[0].score > 0
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
            assert results[i].rank == i + 1

    def test_keyword_search_helper(self):
        # Uses last built index
        results = keyword_search("AuthManager", top_k=1)
        assert len(results) == 1
        assert results[0].symbol == "AuthManager"


# ---------------------------------------------------------------------------
# Serialization & Persistence
# ---------------------------------------------------------------------------

class TestBM25Serialization:
    def test_save_and_load(self, tmp_path: Path):
        chunks = _create_sample_chunks()
        index = BM25Index().build(chunks)
        save_file = tmp_path / "bm25_index.json"

        index.save(save_file)
        assert save_file.is_file()

        loaded_index = BM25Index.load(save_file)
        assert len(loaded_index) == len(index)

        # Search results must be identical
        orig_results = index.search("user profile", top_k=5)
        loaded_results = loaded_index.search("user profile", top_k=5)

        assert len(orig_results) == len(loaded_results)
        for r1, r2 in zip(orig_results, loaded_results):
            assert r1.document_id == r2.document_id
            assert r1.score == r2.score
            assert r1.file == r2.file
            assert r1.start_line == r2.start_line
            assert r1.end_line == r2.end_line
            assert r1.symbol == r2.symbol
            assert r1.symbol_id == r2.symbol_id
            assert r1.text == r2.text


# ---------------------------------------------------------------------------
# Demo Repository Integration Tests
# ---------------------------------------------------------------------------

class TestBM25DemoRepoIntegration:
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    @pytest.fixture(scope="class")
    @classmethod
    def demo_bm25_index(cls):
        if not cls.DEMO_ROOT.is_dir():
            pytest.skip("data/demo_repo not found")
        repo_idx = scan_repository(str(cls.DEMO_ROOT))
        chunk_idx = build_chunks(repo_idx)
        index = BM25Index().build(chunk_idx)
        return repo_idx, chunk_idx, index

    def _verify_grounding(self, results: list[KeywordSearchResult], repo_root: Path):
        assert len(results) > 0
        file_cache: dict[str, list[str]] = {}

        for res in results:
            abs_path = repo_root / res.file
            assert abs_path.is_file(), f"Result file {res.file} does not exist"
            assert res.start_line >= 1
            assert res.end_line >= res.start_line

            if res.file not in file_cache:
                file_cache[res.file] = abs_path.read_text(encoding="utf-8").splitlines()
            lines = file_cache[res.file]

            expected_text = "\n".join(lines[res.start_line - 1 : res.end_line])
            assert res.text == expected_text, (
                f"Source mismatch for {res.document_id} lines {res.start_line}..{res.end_line}"
            )

    def test_query_get_user_profile(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("get user profile", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_symbols = [r.symbol for r in results]
        assert any(s in ("get_user_profile", "get_user_profile_endpoint", "UserService") for s in top_symbols)

    def test_query_find_user_by_id(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("find user by id", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_symbols = [r.symbol for r in results]
        assert "find_by_id" in top_symbols or "UserRepository" in top_symbols

    def test_query_user_authentication(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("user authentication", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_files = [r.file for r in results]
        assert any("auth" in f or "sample" in f for f in top_files)

    def test_query_database_execute_query(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("database execute query", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_symbols = [r.symbol for r in results]
        assert any("execute" in s or "DatabaseConnection" in s or "database" in r.file for s, r in zip(top_symbols, results))

    def test_query_update_user_status(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("update user status", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_symbols = [r.symbol for r in results]
        assert any("update_status" in s or "update_user_status" in s for s in top_symbols)

    def test_query_validate_authentication_token(self, demo_bm25_index):
        repo_idx, _, index = demo_bm25_index
        results = index.search("validate authentication token", top_k=5)
        self._verify_grounding(results, Path(repo_idx.root))
        top_files = [r.file for r in results]
        assert any("auth" in f for f in top_files)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

class TestBM25Benchmark:
    DEMO_ROOT = Path(__file__).parent.parent.parent / "data" / "demo_repo"

    def test_bm25_performance_benchmark(self):
        repo_idx = scan_repository(str(self.DEMO_ROOT))
        chunk_idx = build_chunks(repo_idx)
        doc_count = len(chunk_idx)
        assert doc_count > 0

        # Benchmark indexing
        t0 = time.perf_counter()
        index = BM25Index().build(chunk_idx)
        indexing_time_ms = (time.perf_counter() - t0) * 1000.0

        # Benchmark querying
        queries = [
            "get user profile",
            "find user by id",
            "user authentication",
            "database execute query",
            "update user status",
            "validate authentication token",
        ]

        latencies_ms: list[float] = []
        for q in queries:
            t_q = time.perf_counter()
            results = index.search(q, top_k=10)
            latencies_ms.append((time.perf_counter() - t_q) * 1000.0)
            assert len(results) > 0

        avg_latency_ms = sum(latencies_ms) / len(latencies_ms)

        # Output metrics
        print(f"\n[BM25 BENCHMARK] Documents indexed: {doc_count}")
        print(f"[BM25 BENCHMARK] Indexing time: {indexing_time_ms:.2f} ms")
        print(f"[BM25 BENCHMARK] Average query latency: {avg_latency_ms:.2f} ms (max: {max(latencies_ms):.2f} ms)")

        # Assert performance bounds
        assert indexing_time_ms < 500.0, f"Indexing too slow: {indexing_time_ms} ms"
        assert avg_latency_ms < 50.0, f"Query latency too high: {avg_latency_ms} ms"
