"""Data models for structure-aware code chunking.

Each chunk represents a structural code unit (module, class, function, method)
preserving exact source line numbers derived from AST analysis.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

from pydantic import BaseModel, Field


class ChunkKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class CodeChunk(BaseModel):
    """A single structure-aware code chunk.

    Guarantees:
    - start_line and end_line are exact 1-based source lines from the file.
    - text is the exact source slice [start_line:end_line] from the file.
    - chunk_id is deterministic and stable across scans.
    """

    chunk_id: str = Field(description="Deterministic unique ID for the chunk.")
    file: str = Field(description="Path relative to repository root.")
    symbol_id: str = Field(
        description="Associated symbol ID from AST or module ID.",
    )
    symbol: str = Field(description="Name of the symbol or module.")
    kind: str = Field(description="Chunk kind: module | class | function | method.")
    start_line: int = Field(description="1-based starting line number in source file.")
    end_line: int = Field(description="1-based ending line number in source file.")
    text: str = Field(description="Exact source code content for the line range.")
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structural metadata: module, containing_class, signature, docstring, imports.",
    )

    model_config = {"frozen": True}


class ChunkIndex(BaseModel):
    """Complete collection of generated chunks for a repository."""

    root: str = Field(description="Absolute path to repository root.")
    chunks: List[CodeChunk] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self) -> Iterator[CodeChunk]:
        return iter(self.chunks)

    def all_chunks(self) -> List[CodeChunk]:
        return list(self.chunks)

    def get_chunk(self, chunk_id: str) -> Optional[CodeChunk]:
        """Return the chunk with the specified chunk_id, or None."""
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None

    def get_chunks_for_symbol(self, symbol_id: str) -> List[CodeChunk]:
        """Return all chunks associated with symbol_id (including split parts)."""
        return [c for c in self.chunks if c.symbol_id == symbol_id]

    def get_chunks_for_file(self, file: str) -> List[CodeChunk]:
        """Return all chunks originating from a given relative file path."""
        return [c for c in self.chunks if c.file == file]

    def get_chunks_by_kind(self, kind: str | ChunkKind) -> List[CodeChunk]:
        """Return all chunks of a specific kind."""
        target_kind = kind.value if isinstance(kind, ChunkKind) else kind
        return [c for c in self.chunks if c.kind == target_kind]

    model_config = {"frozen": False}
