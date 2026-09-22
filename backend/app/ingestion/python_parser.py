"""AST-based Python source file parser.

Extracts symbols (classes, functions, async functions, methods) and import
statements from a single Python source file.  All source locations come
directly from the AST node attributes ``lineno``, ``end_lineno``,
``col_offset``, ``end_col_offset``.  No line numbers are ever fabricated.

Syntax errors are captured as ``ParseDiagnostic`` entries rather than
propagated, so a single broken file cannot crash the whole scan.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

from backend.app.ingestion.models import (
    ImportedName,
    ModuleIndex,
    ParseDiagnostic,
    Symbol,
    SymbolKind,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_docstring(node: ast.AST) -> Optional[str]:
    """Return the first string-literal body statement, or None."""
    if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    body = getattr(node, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        val = body[0].value.value
        if isinstance(val, str):
            return textwrap.dedent(val).strip()
    return None


def _node_signature(node: ast.stmt, source_lines: List[str]) -> str:
    """Reconstruct the def/class header line from source."""
    start = node.lineno - 1           # AST lines are 1-based
    end_header = start
    # Scan forward until the line containing ':'
    for i in range(start, min(start + 20, len(source_lines))):
        line = source_lines[i]
        if i == start and isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            # Include decorator lines already counted separately; skip them
            pass
        if ":" in line:
            end_header = i
            break
    header = " ".join(source_lines[start:end_header + 1]).strip()
    # Truncate at the colon to avoid multi-line bodies leaking in
    colon_pos = header.rfind(":")
    if colon_pos != -1:
        header = header[:colon_pos + 1]
    return header


def _decorator_names(node: ast.stmt) -> List[str]:
    """Return decorator expressions as source text."""
    decorators: List[str] = []
    for dec in getattr(node, "decorator_list", []):
        decorators.append(ast.unparse(dec))
    return decorators


def _make_symbol_id(relative_file: str, qualified_name: str) -> str:
    return f"{relative_file}::{qualified_name}"


def _determine_kind(
    node: ast.stmt,
    parent_node: Optional[ast.stmt],
) -> SymbolKind:
    is_async = isinstance(node, ast.AsyncFunctionDef)
    if isinstance(parent_node, ast.ClassDef):
        return SymbolKind.ASYNC_METHOD if is_async else SymbolKind.METHOD
    if is_async:
        return SymbolKind.ASYNC_FUNCTION
    return SymbolKind.FUNCTION


# ---------------------------------------------------------------------------
# Recursive symbol visitor
# ---------------------------------------------------------------------------

class _SymbolVisitor(ast.NodeVisitor):
    """Walks the AST collecting every class and function definition."""

    def __init__(self, relative_file: str, source_lines: List[str]) -> None:
        self.relative_file = relative_file
        self.source_lines = source_lines
        self.symbols: List[Symbol] = []
        # Stack of (qualified_name, symbol_id, ast_node) for parent tracking
        self._scope_stack: List[Tuple[str, str, ast.stmt]] = []

    # ------------------------------------------------------------------
    def _current_parent_id(self) -> Optional[str]:
        if self._scope_stack:
            return self._scope_stack[-1][1]
        return None

    def _current_parent_node(self) -> Optional[ast.stmt]:
        if self._scope_stack:
            return self._scope_stack[-1][2]
        return None

    def _push(self, name: str, symbol_id: str, node: ast.stmt) -> None:
        self._scope_stack.append((name, symbol_id, node))

    def _pop(self) -> None:
        self._scope_stack.pop()

    def _qualified_name(self, name: str) -> str:
        if self._scope_stack:
            return f"{self._scope_stack[-1][0]}.{name}"
        return name

    # ------------------------------------------------------------------
    def _visit_callable(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        parent_node = self._current_parent_node()
        qname = self._qualified_name(node.name)
        sid = _make_symbol_id(self.relative_file, qname)

        # end_lineno / end_col_offset are available from Python 3.8+
        sym = Symbol(
            symbol_id=sid,
            name=node.name,
            qualified_name=qname,
            kind=_determine_kind(node, parent_node),
            file=self.relative_file,
            start_line=node.lineno,
            end_line=node.end_lineno,
            start_column=node.col_offset,
            end_column=node.end_col_offset,
            parent_symbol=self._current_parent_id(),
            signature=_node_signature(node, self.source_lines),
            docstring=_get_docstring(node),
            decorators=_decorator_names(node),
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )
        self.symbols.append(sym)
        self._push(qname, sid, node)
        self.generic_visit(node)
        self._pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qname = self._qualified_name(node.name)
        sid = _make_symbol_id(self.relative_file, qname)

        sym = Symbol(
            symbol_id=sid,
            name=node.name,
            qualified_name=qname,
            kind=SymbolKind.CLASS,
            file=self.relative_file,
            start_line=node.lineno,
            end_line=node.end_lineno,
            start_column=node.col_offset,
            end_column=node.end_col_offset,
            parent_symbol=self._current_parent_id(),
            signature=_node_signature(node, self.source_lines),
            docstring=_get_docstring(node),
            decorators=_decorator_names(node),
            is_async=False,
        )
        self.symbols.append(sym)
        self._push(qname, sid, node)
        self.generic_visit(node)
        self._pop()


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

def _extract_imports(tree: ast.Module) -> List[ImportedName]:
    imports: List[ImportedName] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(ImportedName(
                    module=None,
                    name=alias.name,
                    alias=alias.asname,
                    line=node.lineno,
                ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(ImportedName(
                    module=module,
                    name=alias.name,
                    alias=alias.asname,
                    line=node.lineno,
                ))
    return imports


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_symbols(source: str, relative_file: str) -> ModuleIndex:
    """Parse *source* text and return a :class:`ModuleIndex`.

    On ``SyntaxError`` a diagnostic is recorded and an empty index is returned
    — parsing of other files continues uninterrupted.
    """
    try:
        tree = ast.parse(source, filename=relative_file, type_comments=False)
    except SyntaxError as exc:
        diag = ParseDiagnostic(
            file=relative_file,
            message=str(exc.msg),
            line=exc.lineno,
            column=exc.offset,
        )
        return ModuleIndex(file=relative_file, diagnostics=[diag])

    source_lines = source.splitlines()

    # Module-level symbol
    module_doc = _get_docstring(tree)

    # Walk all class/function definitions
    visitor = _SymbolVisitor(relative_file, source_lines)
    visitor.visit(tree)

    # Imports
    imports = _extract_imports(tree)

    return ModuleIndex(
        file=relative_file,
        symbols=visitor.symbols,
        imports=imports,
        module_docstring=module_doc,
        diagnostics=[],
    )
