"""Deterministic BM25 lexical retrieval engine.

Indexes CodeChunk objects using code-aware tokenization and scores queries
using the Robertson-Spärck Jones Okapi BM25 ranking algorithm with positive IDF.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field

from backend.app.retrieval.models import ChunkIndex, CodeChunk
from backend.app.retrieval.tokenizer import tokenize_code

# Global cache for the most recently built or loaded BM25 index
_LAST_BM25_INDEX: Optional[BM25Index] = None


class KeywordSearchResult(BaseModel):
    """Structured keyword search result with exact source grounding."""

    document_id: str = Field(description="Unique ID of the matched chunk.")
    score: float = Field(description="Deterministic BM25 relevance score.")
    file: str = Field(description="Relative file path.")
    start_line: int = Field(description="1-based starting line number.")
    end_line: int = Field(description="1-based ending line number.")
    symbol: str = Field(description="Symbol name or module name.")
    symbol_id: str = Field(description="Associated symbol ID.")
    text: str = Field(description="Exact source code text of the chunk.")
    rank: int = Field(description="1-based ranking position (1 = highest score).")
    context: Dict[str, Any] = Field(default_factory=dict)
    kind: str = Field(default="unknown")

    model_config = {"frozen": True}


class BM25Index:
    """In-memory deterministic BM25 index for CodeChunk documents."""

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.documents: List[CodeChunk] = []
        self.doc_ids: Set[str] = set()
        self.doc_lengths: List[int] = []
        self.avgdl: float = 0.0
        self.total_docs: int = 0
        # Inverted index: term -> {doc_idx: term_frequency}
        self.inverted_index: Dict[str, Dict[int, int]] = {}
        # Document frequency: term -> number of docs containing term
        self.df: Dict[str, int] = {}
        # Precomputed positive Robertson-Spärck Jones IDF
        self.idf: Dict[str, float] = {}

    def __len__(self) -> int:
        return self.total_docs

    def build(self, documents: Union[List[CodeChunk], ChunkIndex]) -> BM25Index:
        """Build the BM25 index from a collection of CodeChunk objects.

        Deduplicates documents by chunk_id.
        """
        global _LAST_BM25_INDEX
        chunk_list: List[CodeChunk] = (
            documents.all_chunks() if isinstance(documents, ChunkIndex) else list(documents)
        )

        self.documents = []
        self.doc_ids = set()
        self.doc_lengths = []
        self.inverted_index = {}
        self.df = {}
        self.idf = {}

        if not chunk_list:
            self.total_docs = 0
            self.avgdl = 0.0
            _LAST_BM25_INDEX = self
            return self

        # Deduplicate while preserving deterministic order
        unique_chunks: List[CodeChunk] = []
        for chunk in chunk_list:
            if chunk.chunk_id not in self.doc_ids:
                self.doc_ids.add(chunk.chunk_id)
                unique_chunks.append(chunk)

        self.documents = unique_chunks
        self.total_docs = len(unique_chunks)

        total_length = 0
        for doc_idx, chunk in enumerate(self.documents):
            # Formulate rich searchable document representation
            # Boost symbol name and signature so exact symbol matches rank highest
            ctx = chunk.context or {}
            sig = str(ctx.get("signature", ""))
            docstring = str(ctx.get("docstring", ""))
            mod = str(ctx.get("module", ""))
            cls_name = str(ctx.get("containing_class", "") or "")
            imports = " ".join(ctx.get("relevant_imports", []) or [])

            content = (
                f"{chunk.symbol} {chunk.symbol} {sig} {sig} "
                f"{cls_name} {mod} {docstring} {imports} {chunk.text}"
            )
            tokens = tokenize_code(content)
            doc_len = len(tokens)
            self.doc_lengths.append(doc_len)
            total_length += doc_len

            term_counts = Counter(tokens)
            for term, count in term_counts.items():
                if term not in self.inverted_index:
                    self.inverted_index[term] = {}
                    self.df[term] = 0
                self.inverted_index[term][doc_idx] = count
                self.df[term] += 1

        self.avgdl = total_length / self.total_docs if self.total_docs > 0 else 0.0

        # Precompute positive Robertson-Spärck Jones IDF
        for term, doc_freq in self.df.items():
            self.idf[term] = math.log(
                1.0 + (self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5)
            )

        _LAST_BM25_INDEX = self
        return self

    def search(self, query: str, top_k: int = 10) -> List[KeywordSearchResult]:
        """Search the indexed chunks using BM25 scoring.

        Handles:
        - empty or whitespace query -> returns []
        - empty index -> returns []
        - unknown terms -> returns []
        - top_k larger than result count -> returns all matching documents
        """
        if not query or not query.strip() or self.total_docs == 0 or top_k <= 0:
            return []

        query_tokens = tokenize_code(query)
        if not query_tokens:
            return []

        scores: Dict[int, float] = {}

        for q_term in query_tokens:
            if q_term not in self.inverted_index:
                continue

            q_idf = self.idf[q_term]
            postings = self.inverted_index[q_term]

            for doc_idx, freq in postings.items():
                doc_len = self.doc_lengths[doc_idx]
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (
                    1.0 - self.b + self.b * (doc_len / self.avgdl if self.avgdl > 0 else 1.0)
                )
                score = q_idf * (numerator / denominator)
                scores[doc_idx] = scores.get(doc_idx, 0.0) + score

        if not scores:
            return []

        # Sort by score descending, then by chunk_id ascending for 100% deterministic tie-breaking
        sorted_docs = sorted(
            scores.items(),
            key=lambda item: (-item[1], self.documents[item[0]].chunk_id),
        )

        results: List[KeywordSearchResult] = []
        for rank, (doc_idx, score) in enumerate(sorted_docs[:top_k], start=1):
            doc = self.documents[doc_idx]
            results.append(
                KeywordSearchResult(
                    document_id=doc.chunk_id,
                    score=round(score, 4),
                    file=doc.file,
                    start_line=doc.start_line,
                    end_line=doc.end_line,
                    symbol=doc.symbol,
                    symbol_id=doc.symbol_id,
                    text=doc.text,
                    rank=rank,
                    context=doc.context,
                    kind=doc.kind,
                )
            )

        return results

    def save(self, path: Union[str, Path]) -> None:
        """Serialize the index and documents to a JSON file."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "k1": self.k1,
            "b": self.b,
            "total_docs": self.total_docs,
            "avgdl": self.avgdl,
            "doc_lengths": self.doc_lengths,
            "df": self.df,
            "idf": self.idf,
            "inverted_index": {k: {str(d): c for d, c in v.items()} for k, v in self.inverted_index.items()},
            "documents": [doc.model_dump() for doc in self.documents],
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    @classmethod
    def load(cls, path: Union[str, Path]) -> BM25Index:
        """Load and reconstruct a BM25Index from a JSON file."""
        global _LAST_BM25_INDEX
        in_path = Path(path)
        with open(in_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        idx = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        idx.total_docs = data["total_docs"]
        idx.avgdl = data["avgdl"]
        idx.doc_lengths = data["doc_lengths"]
        idx.df = data["df"]
        idx.idf = data["idf"]
        idx.inverted_index = {
            k: {int(d): c for d, c in v.items()} for k, v in data["inverted_index"].items()
        }
        idx.documents = [CodeChunk(**d) for d in data["documents"]]
        idx.doc_ids = {doc.chunk_id for doc in idx.documents}

        _LAST_BM25_INDEX = idx
        return idx


def keyword_search(
    query: str,
    top_k: int = 10,
    index: Optional[BM25Index] = None,
) -> List[KeywordSearchResult]:
    """Search code chunks using the BM25 index."""
    idx = index or _LAST_BM25_INDEX
    if idx is None:
        return []
    return idx.search(query=query, top_k=top_k)
