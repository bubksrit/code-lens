"""Input, output, and metadata schemas for controlled agent investigation tools.

Every tool has strict Pydantic v2 schemas guaranteeing typed inputs,
bounded outputs, and repository-relative source grounding.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.retrieval.bm25 import KeywordSearchResult
from backend.app.retrieval.models import CodeChunk


# ---------------------------------------------------------------------------
# Generic Tool Execution Result
# ---------------------------------------------------------------------------

class ToolResult(BaseModel):
    """Unified container for tool execution outcomes."""

    success: bool = Field(description="True if execution succeeded; False if an error occurred.")
    tool_name: str = Field(description="Name of the invoked tool.")
    data: Optional[Any] = Field(
        default=None,
        description="Structured output payload when successful.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Human-readable error description when unsuccessful.",
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Tool Input Schemas
# ---------------------------------------------------------------------------

class KeywordSearchInput(BaseModel):
    """Input for BM25 lexical search across code chunks."""

    query: str = Field(description="Search terms or code identifier.", min_length=1)
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of chunks to return (1-50, default 10).",
    )


class SymbolLookupInput(BaseModel):
    """Input for symbol resolution by simple name, qualified name, or symbol ID."""

    symbol_query: str = Field(
        description="Symbol name (e.g. 'get_user_profile') or symbol ID (e.g. 'app/routes.py::get_user_profile_endpoint').",
        min_length=1,
    )


class FindCallersInput(BaseModel):
    """Input for finding incoming static call graph edges to a symbol."""

    symbol_id: str = Field(description="Target symbol ID to find callers for.", min_length=1)
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum caller edges to return (1-50, default 20).",
    )


class FindCalleesInput(BaseModel):
    """Input for finding outgoing static call graph edges from a symbol."""

    symbol_id: str = Field(description="Source symbol ID to find callees for.", min_length=1)
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum callee edges to return (1-50, default 20).",
    )


class GetSourceInput(BaseModel):
    """Input for retrieving exact source code lines from a file."""

    file: str = Field(
        description="Repository-relative file path (e.g. 'app/routes.py').",
        min_length=1,
    )
    start_line: int = Field(ge=1, description="1-based starting line number.")
    end_line: int = Field(ge=1, description="1-based ending line number.")


class GetChunkInput(BaseModel):
    """Input for retrieving a specific CodeChunk by its unique chunk_id."""

    chunk_id: str = Field(description="Unique chunk identifier.", min_length=1)


# ---------------------------------------------------------------------------
# Tool Output Schemas
# ---------------------------------------------------------------------------

class KeywordSearchOutput(BaseModel):
    """Structured response for keyword search."""

    query: str
    results: List[KeywordSearchResult]
    total_found: int


class SymbolItem(BaseModel):
    """Detailed metadata for a discovered symbol."""

    symbol_id: str
    name: str
    qualified_name: str
    kind: str
    file: str
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)
    parent_symbol: Optional[str] = None


class SymbolLookupOutput(BaseModel):
    """Structured response for symbol lookup."""

    query: str
    symbols: List[SymbolItem]
    total_found: int


class CallEdgeItem(BaseModel):
    """A call relationship with certainty and source location."""

    caller: str
    callee: str
    file: str
    line: int
    resolution: str
    call_expr: Optional[str] = None


class FindCallersOutput(BaseModel):
    """Structured response for caller lookup."""

    symbol_id: str
    callers: List[CallEdgeItem]
    total_found: int


class FindCalleesOutput(BaseModel):
    """Structured response for callee lookup."""

    symbol_id: str
    callees: List[CallEdgeItem]
    total_found: int


class GetSourceOutput(BaseModel):
    """Structured response for exact source line retrieval."""

    file: str
    start_line: int
    end_line: int
    text: str
    total_lines: int


class GetChunkOutput(BaseModel):
    """Structured response for chunk retrieval."""

    chunk: CodeChunk


# ---------------------------------------------------------------------------
# Tool Definition Metadata (for future LLM Planner consumption)
# ---------------------------------------------------------------------------

class ToolDefinition(BaseModel):
    """LLM-compatible tool declaration."""

    name: str
    description: str
    parameters: Dict[str, Any]
