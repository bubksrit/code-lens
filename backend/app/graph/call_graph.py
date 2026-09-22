"""Static call graph builder and query engine.

Constructs directed call graphs from Python ASTs with explicit edge resolution.
Never fabricates calls or claims dynamic invocations are resolved.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.app.graph.models import CallEdge, CallGraph, CallResolution
from backend.app.graph.resolver import SymbolResolver
from backend.app.ingestion.models import ModuleIndex, RepositoryIndex, Symbol

# Module-level cache for the most recently built CallGraph
_LAST_CALL_GRAPH: Optional[CallGraph] = None


class _CallVisitor(ast.NodeVisitor):
    """Walks an AST tree to discover all call sites inside symbols."""

    def __init__(
        self,
        module: ModuleIndex,
        resolver: SymbolResolver,
    ) -> None:
        self.module = module
        self.resolver = resolver
        self.edges: List[CallEdge] = []
        # Stack of enclosing callable symbols
        self._caller_stack: List[Symbol] = []
        # Local variable type tracking inside current function: var_name -> class_name
        self._local_types: Dict[str, str] = {}
        # Class attribute type tracking inside class: attr_name -> class_name
        self._class_attr_types: Dict[str, str] = {}

    def _find_symbol_for_node(self, node: ast.AST) -> Optional[Symbol]:
        """Find the matching symbol in current module for an AST def node."""
        if not hasattr(node, "lineno") or not hasattr(node, "name"):
            return None
        for sym in self.module.symbols:
            if sym.name == node.name and sym.start_line == node.lineno:
                return sym
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_attr_types = dict(self._class_attr_types)
        # Scan for default class attributes or self assignments
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Assign):
                        for tgt in sub.targets:
                            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name):
                                if tgt.value.id == "self":
                                    inferred = self._infer_type_from_expr(sub.value)
                                    if inferred:
                                        self._class_attr_types[tgt.attr] = inferred

        self.generic_visit(node)
        self._class_attr_types = old_attr_types

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        sym = self._find_symbol_for_node(node)
        if sym is not None:
            self._caller_stack.append(sym)
            old_local_types = dict(self._local_types)
            self._local_types = dict(self._class_attr_types)
            # Scan local variable assignments in this function
            self._scan_local_assignments(node)
            self.generic_visit(node)
            self._local_types = old_local_types
            self._caller_stack.pop()
        else:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        sym = self._find_symbol_for_node(node)
        if sym is not None:
            self._caller_stack.append(sym)
            old_local_types = dict(self._local_types)
            self._local_types = dict(self._class_attr_types)
            self._scan_local_assignments(node)
            self.generic_visit(node)
            self._local_types = old_local_types
            self._caller_stack.pop()
        else:
            self.generic_visit(node)

    def _infer_type_from_expr(self, expr: ast.AST) -> Optional[str]:
        """Infer simple class name from constructor call or BoolOp (e.g. repo or UserRepository())."""
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            return expr.func.id
        elif isinstance(expr, ast.BoolOp):
            # e.g. repository or UserRepository()
            for val in expr.values:
                inferred = self._infer_type_from_expr(val)
                if inferred:
                    return inferred
        return None

    def _scan_local_assignments(self, func_node: ast.AST) -> None:
        """Scan function body for simple variable instantiation assignments."""
        for item in getattr(func_node, "body", []):
            if isinstance(item, ast.Assign):
                inferred = self._infer_type_from_expr(item.value)
                if inferred:
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            self._local_types[target.id] = inferred

    def visit_Call(self, node: ast.Call) -> None:
        if not self._caller_stack:
            # Call outside any function (module level)
            caller_id = f"{self.module.file}::module"
        else:
            caller_id = self._caller_stack[-1].symbol_id

        caller_sym = self._caller_stack[-1] if self._caller_stack else Symbol(
            symbol_id=caller_id,
            name=self.module.file,
            qualified_name=self.module.file,
            kind="module",
            file=self.module.file,
            start_line=1,
            end_line=1,
            start_column=0,
            end_column=0,
            signature="",
        )

        resolved_targets = self.resolver.resolve_call(
            call_node=node,
            caller_symbol=caller_sym,
            current_module=self.module,
            local_types=self._local_types,
        )

        call_expr_str = ""
        try:
            call_expr_str = ast.unparse(node)
        except Exception:
            call_expr_str = ""

        for callee_id, resolution in resolved_targets:
            edge = CallEdge(
                caller=caller_id,
                callee=callee_id,
                file=self.module.file,
                line=getattr(node, "lineno", 1),
                resolution=resolution.value,
                call_expr=call_expr_str,
            )
            self.edges.append(edge)

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_call_graph(repository_index: RepositoryIndex) -> CallGraph:
    """Build a complete static CallGraph for all modules in repository_index.

    Args:
        repository_index: Complete index of repository files and symbols.

    Returns:
        CallGraph instance containing all resolved and unresolved edges.
    """
    global _LAST_CALL_GRAPH
    resolver = SymbolResolver(repository_index)
    all_edges: List[CallEdge] = []
    root_path = Path(repository_index.root)

    for module in repository_index.modules:
        file_path = root_path / module.file
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=module.file)
        except Exception:
            continue

        visitor = _CallVisitor(module=module, resolver=resolver)
        visitor.visit(tree)
        all_edges.extend(visitor.edges)

    graph = CallGraph(edges=all_edges)
    _LAST_CALL_GRAPH = graph
    return graph


def find_callers(symbol_id: str, graph: Optional[CallGraph] = None) -> List[CallEdge]:
    """Return all incoming call edges targeting symbol_id."""
    g = graph or _LAST_CALL_GRAPH
    if g is None:
        return []
    return g.find_callers(symbol_id)


def find_callees(symbol_id: str, graph: Optional[CallGraph] = None) -> List[CallEdge]:
    """Return all outgoing call edges originating from symbol_id."""
    g = graph or _LAST_CALL_GRAPH
    if g is None:
        return []
    return g.find_callees(symbol_id)


def find_path(
    source_symbol: str,
    target_symbol: str,
    graph: Optional[CallGraph] = None,
    include_unresolved: bool = False,
) -> Optional[List[CallEdge]]:
    """Find the shortest directed path between source_symbol and target_symbol."""
    g = graph or _LAST_CALL_GRAPH
    if g is None:
        return None
    return g.find_path(
        source_symbol=source_symbol,
        target_symbol=target_symbol,
        include_unresolved=include_unresolved,
    )
