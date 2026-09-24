"""Controlled agent investigation tools.

Provides typed, deterministic, and sandboxed tools for inspecting an indexed
Python repository. Enforces bounded result sizes, exact source grounding,
and strict path traversal prevention.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import ValidationError

from backend.app.agent.models import (
    CallEdgeItem,
    FindCalleesInput,
    FindCalleesOutput,
    FindCallersInput,
    FindCallersOutput,
    GetChunkInput,
    GetChunkOutput,
    GetSourceInput,
    GetSourceOutput,
    KeywordSearchInput,
    KeywordSearchOutput,
    SymbolItem,
    SymbolLookupInput,
    SymbolLookupOutput,
    ToolDefinition,
    ToolResult,
)
from backend.app.graph.call_graph import CallGraph, build_call_graph
from backend.app.ingestion.models import RepositoryIndex, Symbol
from backend.app.ingestion.scanner import scan_repository
from backend.app.retrieval.bm25 import BM25Index
from backend.app.retrieval.chunker import build_chunks
from backend.app.retrieval.models import ChunkIndex


class ToolContext:
    """Shared index dependencies and sandbox configuration for agent tools."""

    def __init__(
        self,
        repo_root: Union[str, Path],
        repository_index: RepositoryIndex,
        chunk_index: ChunkIndex,
        bm25_index: BM25Index,
        call_graph: CallGraph,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.repository_index = repository_index
        self.chunk_index = chunk_index
        self.bm25_index = bm25_index
        self.call_graph = call_graph


# ---------------------------------------------------------------------------
# Individual Tool Handlers
# ---------------------------------------------------------------------------

def execute_keyword_search(ctx: ToolContext, args: KeywordSearchInput) -> ToolResult:
    """Execute deterministic BM25 lexical search over indexed code chunks."""
    results = ctx.bm25_index.search(query=args.query, top_k=args.top_k)
    output = KeywordSearchOutput(
        query=args.query,
        results=results,
        total_found=len(results),
    )
    return ToolResult(
        success=True,
        tool_name="keyword_search",
        data=output,
    )


def execute_symbol_lookup(ctx: ToolContext, args: SymbolLookupInput) -> ToolResult:
    """Look up exact symbol metadata by symbol_id, qualified name, or simple name."""
    query = args.symbol_query.strip()
    if not query:
        return ToolResult(
            success=False,
            tool_name="symbol_lookup",
            error="symbol_query cannot be empty.",
        )

    all_symbols = ctx.repository_index.all_symbols()
    matched_symbols: List[Symbol] = []

    # 1. Exact symbol_id match
    for s in all_symbols:
        if s.symbol_id == query:
            matched_symbols = [s]
            break

    # 2. Exact qualified name match
    if not matched_symbols:
        matched_symbols = [s for s in all_symbols if s.qualified_name == query]

    # 3. Simple name match (exact case, then case-insensitive)
    if not matched_symbols:
        matched_symbols = [s for s in all_symbols if s.name == query]

    if not matched_symbols:
        q_low = query.lower()
        matched_symbols = [s for s in all_symbols if s.name.lower() == q_low]

    if not matched_symbols:
        return ToolResult(
            success=False,
            tool_name="symbol_lookup",
            error=f"Symbol '{query}' was not found in the repository index.",
        )

    items = [
        SymbolItem(
            symbol_id=s.symbol_id,
            name=s.name,
            qualified_name=s.qualified_name,
            kind=s.kind.value if hasattr(s.kind, "value") else str(s.kind),
            file=s.file,
            start_line=s.start_line,
            end_line=s.end_line,
            signature=s.signature,
            docstring=s.docstring,
            decorators=s.decorators,
            parent_symbol=s.parent_symbol,
        )
        for s in matched_symbols
    ]

    return ToolResult(
        success=True,
        tool_name="symbol_lookup",
        data=SymbolLookupOutput(
            query=query,
            symbols=items,
            total_found=len(items),
        ),
    )


def execute_find_callers(ctx: ToolContext, args: FindCallersInput) -> ToolResult:
    """Find incoming call edges to a symbol from the static call graph."""
    edges = ctx.call_graph.find_callers(args.symbol_id)
    bounded_edges = edges[: args.limit]

    items = [
        CallEdgeItem(
            caller=e.caller,
            callee=e.callee,
            file=e.file,
            line=e.line,
            resolution=e.resolution,
            call_expr=e.call_expr,
        )
        for e in bounded_edges
    ]

    return ToolResult(
        success=True,
        tool_name="find_callers",
        data=FindCallersOutput(
            symbol_id=args.symbol_id,
            callers=items,
            total_found=len(items),
        ),
    )


def execute_find_callees(ctx: ToolContext, args: FindCalleesInput) -> ToolResult:
    """Find outgoing call edges from a symbol from the static call graph."""
    edges = ctx.call_graph.find_callees(args.symbol_id)
    bounded_edges = edges[: args.limit]

    items = [
        CallEdgeItem(
            caller=e.caller,
            callee=e.callee,
            file=e.file,
            line=e.line,
            resolution=e.resolution,
            call_expr=e.call_expr,
        )
        for e in bounded_edges
    ]

    return ToolResult(
        success=True,
        tool_name="find_callees",
        data=FindCalleesOutput(
            symbol_id=args.symbol_id,
            callees=items,
            total_found=len(items),
        ),
    )


def execute_get_source(ctx: ToolContext, args: GetSourceInput) -> ToolResult:
    """Retrieve exact source code lines within repository sandbox boundaries."""
    raw_file = args.file.strip()

    # 1. Path traversal security checks
    rel_path = Path(raw_file)
    if rel_path.is_absolute():
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Absolute path '{raw_file}' is not permitted. Provide a repository-relative path.",
        )

    if ".." in rel_path.parts:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Path traversal sequence '..' is not permitted: '{raw_file}'.",
        )

    try:
        abs_path = (ctx.repo_root / rel_path).resolve()
        # Verify resolution stays strictly inside repo_root
        if not abs_path.is_relative_to(ctx.repo_root):
            return ToolResult(
                success=False,
                tool_name="get_source",
                error=f"Access denied: path '{raw_file}' resolves outside the repository sandbox.",
            )
    except Exception as exc:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Invalid path '{raw_file}': {exc}",
        )

    if not abs_path.is_file():
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"File '{raw_file}' does not exist in repository.",
        )

    # 2. Line range validation
    if args.start_line < 1:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Invalid start_line {args.start_line}. Line numbers are 1-based and must be >= 1.",
        )

    if args.end_line < args.start_line:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Invalid line range: start_line ({args.start_line}) cannot exceed end_line ({args.end_line}).",
        )

    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as exc:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"Could not read file '{raw_file}': {exc}",
        )

    total_lines = len(lines)
    if total_lines == 0:
        return ToolResult(
            success=True,
            tool_name="get_source",
            data=GetSourceOutput(
                file=raw_file,
                start_line=1,
                end_line=1,
                text="",
                total_lines=0,
            ),
        )

    if args.start_line > total_lines:
        return ToolResult(
            success=False,
            tool_name="get_source",
            error=f"start_line ({args.start_line}) exceeds total lines in file ({total_lines}).",
        )

    actual_end_line = min(args.end_line, total_lines)
    sliced_lines = lines[args.start_line - 1 : actual_end_line]
    sliced_text = "\n".join(sliced_lines)

    return ToolResult(
        success=True,
        tool_name="get_source",
        data=GetSourceOutput(
            file=raw_file,
            start_line=args.start_line,
            end_line=actual_end_line,
            text=sliced_text,
            total_lines=len(sliced_lines),
        ),
    )


def execute_get_chunk(ctx: ToolContext, args: GetChunkInput) -> ToolResult:
    """Retrieve an exact CodeChunk by its unique chunk_id."""
    chunk = ctx.chunk_index.get_chunk(args.chunk_id)
    if chunk is None:
        return ToolResult(
            success=False,
            tool_name="get_chunk",
            error=f"Chunk '{args.chunk_id}' was not found in the chunk index.",
        )

    return ToolResult(
        success=True,
        tool_name="get_chunk",
        data=GetChunkOutput(chunk=chunk),
    )


# ---------------------------------------------------------------------------
# Tool Registry & Dispatcher
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Registry managing available agent investigation tools."""

    def __init__(self, context: ToolContext) -> None:
        self.context = context
        self._tools: Dict[str, Tuple[Callable[[ToolContext, Any], ToolResult], type]] = {
            "keyword_search": (execute_keyword_search, KeywordSearchInput),
            "symbol_lookup": (execute_symbol_lookup, SymbolLookupInput),
            "find_callers": (execute_find_callers, FindCallersInput),
            "find_callees": (execute_find_callees, FindCalleesInput),
            "get_source": (execute_get_source, GetSourceInput),
            "get_chunk": (execute_get_chunk, GetChunkInput),
        }

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Safely execute a tool with typed input validation and error containment."""
        entry = self._tools.get(tool_name)
        if not entry:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Unknown tool '{tool_name}'. Available: {list(self._tools.keys())}",
            )

        handler, schema_cls = entry
        try:
            validated_args = schema_cls(**arguments)
        except ValidationError as val_err:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Input validation error for tool '{tool_name}': {val_err}",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Invalid arguments for tool '{tool_name}': {exc}",
            )

        try:
            return handler(self.context, validated_args)
        except Exception as exc:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"Internal tool execution error: {exc}",
            )

    # Convenience direct typed methods
    def keyword_search(self, query: str, top_k: int = 10) -> ToolResult:
        return self.execute("keyword_search", {"query": query, "top_k": top_k})

    def symbol_lookup(self, symbol_query: str) -> ToolResult:
        return self.execute("symbol_lookup", {"symbol_query": symbol_query})

    def find_callers(self, symbol_id: str, limit: int = 20) -> ToolResult:
        return self.execute("find_callers", {"symbol_id": symbol_id, "limit": limit})

    def find_callees(self, symbol_id: str, limit: int = 20) -> ToolResult:
        return self.execute("find_callees", {"symbol_id": symbol_id, "limit": limit})

    def get_source(self, file: str, start_line: int, end_line: int) -> ToolResult:
        return self.execute("get_source", {"file": file, "start_line": start_line, "end_line": end_line})

    def get_chunk(self, chunk_id: str) -> ToolResult:
        return self.execute("get_chunk", {"chunk_id": chunk_id})

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return JSON schemas for all registered tools (for future LLM planners)."""
        return [
            ToolDefinition(
                name="keyword_search",
                description="Perform BM25 lexical search over indexed code chunks with source metadata.",
                parameters=KeywordSearchInput.model_json_schema(),
            ),
            ToolDefinition(
                name="symbol_lookup",
                description="Look up exact symbol metadata, signature, and file line range by name or symbol ID.",
                parameters=SymbolLookupInput.model_json_schema(),
            ),
            ToolDefinition(
                name="find_callers",
                description="Find incoming call graph edges targeting a specific symbol ID.",
                parameters=FindCallersInput.model_json_schema(),
            ),
            ToolDefinition(
                name="find_callees",
                description="Find outgoing call graph edges originating from a specific symbol ID.",
                parameters=FindCalleesInput.model_json_schema(),
            ),
            ToolDefinition(
                name="get_source",
                description="Retrieve exact source code text for a validated line range in a repository file.",
                parameters=GetSourceInput.model_json_schema(),
            ),
            ToolDefinition(
                name="get_chunk",
                description="Retrieve an exact CodeChunk including text and context by unique chunk_id.",
                parameters=GetChunkInput.model_json_schema(),
            ),
        ]


def create_tool_registry(repo_root: Union[str, Path]) -> ToolRegistry:
    """Factory creating an initialized ToolRegistry for a repository."""
    root_path = Path(repo_root).resolve()
    repo_idx = scan_repository(str(root_path))
    chunk_idx = build_chunks(repo_idx)
    bm25_idx = BM25Index().build(chunk_idx)
    call_graph = build_call_graph(repo_idx)

    ctx = ToolContext(
        repo_root=root_path,
        repository_index=repo_idx,
        chunk_index=chunk_idx,
        bm25_index=bm25_idx,
        call_graph=call_graph,
    )
    return ToolRegistry(context=ctx)
