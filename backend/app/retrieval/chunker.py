"""Structure-aware code chunking module.

Generates searchable chunks from existing AST symbols in a RepositoryIndex.
Preserves exact source line numbers derived from AST analysis.
Never fabricates or guesses line numbers.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.ingestion.models import (
    ImportedName,
    ModuleIndex,
    RepositoryIndex,
    Symbol,
    SymbolKind,
)
from backend.app.retrieval.models import ChunkIndex, ChunkKind, CodeChunk

# Module-level cache for the most recently built chunk index
_LAST_CHUNK_INDEX: Optional[ChunkIndex] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_to_module_name(relative_file: str) -> str:
    """Convert a relative file path like 'app/routes.py' to 'app.routes'."""
    path_str = relative_file.replace("\\", "/")
    if path_str.endswith(".py"):
        path_str = path_str[:-3]
    return path_str.replace("/", ".").strip(".")


def _format_import(imp: ImportedName) -> str:
    """Format an ImportedName into valid Python import syntax."""
    if imp.module:
        base = f"from {imp.module} import {imp.name}"
    else:
        base = f"import {imp.name}"
    if imp.alias:
        base += f" as {imp.alias}"
    return base


def _find_relevant_imports(
    text: str,
    signature: str,
    module_imports: List[ImportedName],
) -> List[str]:
    """Find imports whose imported name or alias appears in the code text or signature."""
    combined = f"{signature}\n{text}"
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", combined))
    matched: List[str] = []
    for imp in module_imports:
        key = imp.alias if imp.alias else imp.name
        if key in tokens:
            formatted = _format_import(imp)
            if formatted not in matched:
                matched.append(formatted)
    return matched


def _get_containing_class(symbol: Symbol, all_symbols: List[Symbol]) -> Optional[str]:
    """Return the name of the containing class for a method symbol, if any."""
    if symbol.parent_symbol:
        for s in all_symbols:
            if s.symbol_id == symbol.parent_symbol and s.kind == SymbolKind.CLASS:
                return s.name
    # Fallback to qualified name inspection (e.g. 'ClassName.method_name')
    if "." in symbol.qualified_name:
        parts = symbol.qualified_name.split(".")
        return parts[-2]
    return None


def _get_class_methods(class_symbol: Symbol, all_symbols: List[Symbol]) -> List[str]:
    """Return names of methods belonging to the given class."""
    methods: List[str] = []
    for s in all_symbols:
        if s.parent_symbol == class_symbol.symbol_id and s.kind in (
            SymbolKind.METHOD,
            SymbolKind.ASYNC_METHOD,
        ):
            methods.append(s.name)
        elif s.file == class_symbol.file and s.qualified_name.startswith(f"{class_symbol.name}."):
            if s.kind in (SymbolKind.METHOD, SymbolKind.ASYNC_METHOD):
                if s.name not in methods:
                    methods.append(s.name)
    return methods


def _extract_source_slice(source_lines: List[str], start_line: int, end_line: int) -> str:
    """Extract exact source code lines for 1-based start_line and end_line."""
    if not source_lines or start_line < 1:
        return ""
    start_idx = max(0, start_line - 1)
    end_idx = min(len(source_lines), end_line)
    if start_idx >= len(source_lines):
        return ""
    return "\n".join(source_lines[start_idx:end_idx])


# ---------------------------------------------------------------------------
# Deterministic Oversized Function Splitting
# ---------------------------------------------------------------------------

def _find_statement_boundaries(source: str, symbol: Symbol) -> List[Tuple[int, int]]:
    """Find start and end line ranges of top-level statements inside a function AST node."""
    try:
        tree = ast.parse(source, filename=symbol.file)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol.name and node.lineno == symbol.start_line:
                boundaries = []
                for stmt in node.body:
                    start = getattr(stmt, "lineno", None)
                    end = getattr(stmt, "end_lineno", start)
                    if start is not None and end is not None:
                        boundaries.append((start, end))
                return boundaries
    return []


def _split_oversized_function(
    source_lines: List[str],
    symbol: Symbol,
    max_lines: int,
    base_context: Dict[str, Any],
) -> List[CodeChunk]:
    """Split an oversized function into deterministic, non-lossy chunks.

    Guarantees:
    - Exactly covers [symbol.start_line, symbol.end_line] with no gap and no overlap.
    - Preserves symbol_id, symbol, and kind.
    - Deterministic chunk IDs: '<symbol_id>::part_<1-based-index>'.
    - Follows AST statement boundaries where possible.
    """
    total_start = symbol.start_line
    total_end = symbol.end_line
    source_text = "\n".join(source_lines)
    stmt_boundaries = _find_statement_boundaries(source_text, symbol)

    # Compute partition line ranges [p_start, p_end]
    ranges: List[Tuple[int, int]] = []
    current_start = total_start

    if stmt_boundaries:
        # Group statements into ranges <= max_lines
        current_end = current_start
        for s_start, s_end in stmt_boundaries:
            if s_end - current_start + 1 > max_lines and current_end > current_start:
                ranges.append((current_start, current_end))
                current_start = current_end + 1
            current_end = s_end

        if current_start <= total_end:
            ranges.append((current_start, total_end))
    else:
        # Fallback to contiguous line blocks if statement boundaries cannot be parsed
        curr = total_start
        while curr <= total_end:
            part_end = min(curr + max_lines - 1, total_end)
            ranges.append((curr, part_end))
            curr = part_end + 1

    # Ensure last range reaches total_end exactly
    if ranges and ranges[-1][1] < total_end:
        last_start = ranges[-1][0]
        ranges[-1] = (last_start, total_end)

    chunks: List[CodeChunk] = []
    total_parts = len(ranges)
    for idx, (p_start, p_end) in enumerate(ranges, start=1):
        chunk_id = f"{symbol.symbol_id}::part_{idx}"
        chunk_text = _extract_source_slice(source_lines, p_start, p_end)
        part_context = dict(base_context)
        part_context["part"] = idx
        part_context["total_parts"] = total_parts
        part_context["is_split"] = True

        chunks.append(
            CodeChunk(
                chunk_id=chunk_id,
                file=symbol.file,
                symbol_id=symbol.symbol_id,
                symbol=symbol.name,
                kind="method" if symbol.kind in (SymbolKind.METHOD, SymbolKind.ASYNC_METHOD) else "function",
                start_line=p_start,
                end_line=p_end,
                text=chunk_text,
                context=part_context,
            )
        )

    return chunks


# ---------------------------------------------------------------------------
# Core Chunk Generation
# ---------------------------------------------------------------------------

def _chunk_module(
    module: ModuleIndex,
    source_lines: List[str],
    max_lines_per_chunk: int,
) -> Optional[CodeChunk]:
    """Generate a high-level module chunk."""
    total_lines = len(source_lines)
    if total_lines == 0:
        start_line = 1
        end_line = 1
        text = ""
    else:
        start_line = 1
        end_line = min(total_lines, max_lines_per_chunk)
        text = _extract_source_slice(source_lines, start_line, end_line)

    mod_name = _file_to_module_name(module.file)
    context = {
        "module": mod_name,
        "docstring": module.module_docstring,
        "imports": [_format_import(imp) for imp in module.imports],
        "total_lines": total_lines,
    }

    return CodeChunk(
        chunk_id=f"{module.file}::module",
        file=module.file,
        symbol_id=f"{module.file}::module",
        symbol=mod_name,
        kind=ChunkKind.MODULE.value,
        start_line=start_line,
        end_line=end_line,
        text=text,
        context=context,
    )


def _chunk_class(
    symbol: Symbol,
    module: ModuleIndex,
    source_lines: List[str],
) -> CodeChunk:
    """Generate a chunk for a class declaration and body."""
    text = _extract_source_slice(source_lines, symbol.start_line, symbol.end_line)
    mod_name = _file_to_module_name(symbol.file)
    methods = _get_class_methods(symbol, module.symbols)
    relevant_imports = _find_relevant_imports(text, symbol.signature, module.imports)

    context = {
        "module": mod_name,
        "signature": symbol.signature,
        "docstring": symbol.docstring,
        "methods": methods,
        "decorators": symbol.decorators,
        "relevant_imports": relevant_imports,
    }

    return CodeChunk(
        chunk_id=symbol.symbol_id,
        file=symbol.file,
        symbol_id=symbol.symbol_id,
        symbol=symbol.name,
        kind=ChunkKind.CLASS.value,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        text=text,
        context=context,
    )


def _chunk_function(
    symbol: Symbol,
    module: ModuleIndex,
    source_lines: List[str],
    max_lines_per_chunk: int,
) -> List[CodeChunk]:
    """Generate chunk(s) for a function or method, splitting if oversized."""
    text = _extract_source_slice(source_lines, symbol.start_line, symbol.end_line)
    mod_name = _file_to_module_name(symbol.file)
    containing_class = _get_containing_class(symbol, module.symbols)
    relevant_imports = _find_relevant_imports(text, symbol.signature, module.imports)
    is_method = symbol.kind in (SymbolKind.METHOD, SymbolKind.ASYNC_METHOD)
    kind_str = ChunkKind.METHOD.value if is_method else ChunkKind.FUNCTION.value

    base_context = {
        "module": mod_name,
        "containing_class": containing_class,
        "signature": symbol.signature,
        "docstring": symbol.docstring,
        "decorators": symbol.decorators,
        "is_async": symbol.is_async,
        "relevant_imports": relevant_imports,
    }

    num_lines = symbol.end_line - symbol.start_line + 1
    if num_lines > max_lines_per_chunk:
        return _split_oversized_function(
            source_lines=source_lines,
            symbol=symbol,
            max_lines=max_lines_per_chunk,
            base_context=base_context,
        )

    chunk = CodeChunk(
        chunk_id=symbol.symbol_id,
        file=symbol.file,
        symbol_id=symbol.symbol_id,
        symbol=symbol.name,
        kind=kind_str,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        text=text,
        context=base_context,
    )
    return [chunk]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_chunks(
    repository_index: RepositoryIndex,
    max_lines_per_chunk: int = 100,
) -> ChunkIndex:
    """Build a complete collection of structure-aware code chunks from a RepositoryIndex.

    Args:
        repository_index: The RepositoryIndex generated by scanner.scan_repository().
        max_lines_per_chunk: Threshold for splitting oversized functions (default 100).

    Returns:
        ChunkIndex containing all generated chunks.
    """
    global _LAST_CHUNK_INDEX
    root_path = Path(repository_index.root)
    all_chunks: List[CodeChunk] = []

    for module in repository_index.modules:
        file_path = root_path / module.file
        try:
            source_text = file_path.read_text(encoding="utf-8", errors="replace")
            source_lines = source_text.splitlines()
        except OSError:
            source_lines = []

        # 1. Module chunk
        mod_chunk = _chunk_module(module, source_lines, max_lines_per_chunk)
        if mod_chunk is not None:
            all_chunks.append(mod_chunk)

        # 2. Symbol chunks (class, function, method)
        for sym in module.symbols:
            if sym.kind == SymbolKind.CLASS:
                all_chunks.append(_chunk_class(sym, module, source_lines))
            elif sym.kind in (
                SymbolKind.FUNCTION,
                SymbolKind.ASYNC_FUNCTION,
                SymbolKind.METHOD,
                SymbolKind.ASYNC_METHOD,
            ):
                fn_chunks = _chunk_function(
                    symbol=sym,
                    module=module,
                    source_lines=source_lines,
                    max_lines_per_chunk=max_lines_per_chunk,
                )
                all_chunks.extend(fn_chunks)

    index = ChunkIndex(root=repository_index.root, chunks=all_chunks)
    _LAST_CHUNK_INDEX = index
    return index


def get_chunk(
    chunk_id: str,
    chunk_index: Optional[ChunkIndex] = None,
) -> Optional[CodeChunk]:
    """Retrieve a chunk by its chunk_id from chunk_index or the last built index."""
    idx = chunk_index or _LAST_CHUNK_INDEX
    if idx is None:
        return None
    return idx.get_chunk(chunk_id)


def get_chunks_for_symbol(
    symbol_id: str,
    chunk_index: Optional[ChunkIndex] = None,
) -> List[CodeChunk]:
    """Retrieve all chunks matching symbol_id from chunk_index or the last built index."""
    idx = chunk_index or _LAST_CHUNK_INDEX
    if idx is None:
        return []
    return idx.get_chunks_for_symbol(symbol_id)
