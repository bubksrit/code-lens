"""Structure-aware code chunking and BM25 lexical retrieval package."""
from backend.app.retrieval.models import ChunkIndex, ChunkKind, CodeChunk
from backend.app.retrieval.chunker import (
    build_chunks,
    get_chunk,
    get_chunks_for_symbol,
)
from backend.app.retrieval.tokenizer import tokenize_code
from backend.app.retrieval.bm25 import (
    BM25Index,
    KeywordSearchResult,
    keyword_search,
)

__all__ = [
    "ChunkIndex",
    "ChunkKind",
    "CodeChunk",
    "build_chunks",
    "get_chunk",
    "get_chunks_for_symbol",
    "tokenize_code",
    "BM25Index",
    "KeywordSearchResult",
    "keyword_search",
]
