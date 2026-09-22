"""Symbol and call target resolver for Python AST call sites.

Determines target symbol IDs and certainty (exact, probable, unresolved) for:
- local function calls
- imported functions and classes
- method invocations with local type inference
- self-method invocations
- recursive calls
- multi-candidate method resolution
- unresolved dynamic/external calls
"""
from __future__ import annotations

import ast
from typing import Dict, List, Optional, Set, Tuple

from backend.app.graph.models import CallResolution
from backend.app.ingestion.models import (
    ModuleIndex,
    RepositoryIndex,
    Symbol,
    SymbolKind,
)


class SymbolResolver:
    """Resolves AST Call nodes to candidate symbol IDs with explicit certainty."""

    def __init__(self, repository_index: RepositoryIndex) -> None:
        self.repo_index = repository_index
        self._all_symbols = repository_index.all_symbols()

        # Index: symbol_id -> Symbol
        self.by_id: Dict[str, Symbol] = {s.symbol_id: s for s in self._all_symbols}

        # Index: (file, name) -> List[Symbol]
        self.by_file_and_name: Dict[Tuple[str, str], List[Symbol]] = {}
        # Index: (file, qualified_name) -> Symbol
        self.by_file_and_qname: Dict[Tuple[str, str], Symbol] = {}
        # Index: simple_name -> List[Symbol]
        self.by_name: Dict[str, List[Symbol]] = {}
        # Index: module_path -> ModuleIndex
        self.module_by_path: Dict[str, ModuleIndex] = {}

        for sym in self._all_symbols:
            fn_key = (sym.file, sym.name)
            self.by_file_and_name.setdefault(fn_key, []).append(sym)
            self.by_file_and_qname[(sym.file, sym.qualified_name)] = sym
            self.by_name.setdefault(sym.name, []).append(sym)

        for mod in repository_index.modules:
            # Map various module path representations
            # e.g. "app/auth.py" -> "app.auth", "data.demo_repo.app.auth"
            self.module_by_path[mod.file] = mod
            clean_mod = mod.file.replace("\\", "/").removesuffix(".py").replace("/", ".")
            self.module_by_path[clean_mod] = mod
            # Also store suffix matching (e.g. if file is "data/demo_repo/app/auth.py", matches "app.auth")
            parts = clean_mod.split(".")
            for i in range(len(parts)):
                sub_mod = ".".join(parts[i:])
                if sub_mod not in self.module_by_path:
                    self.module_by_path[sub_mod] = mod

    def _resolve_import_symbol(
        self,
        current_module: ModuleIndex,
        imported_name: str,
    ) -> Optional[Symbol]:
        """Resolve a name imported into current_module to its original Symbol."""
        for imp in current_module.imports:
            local_alias = imp.alias if imp.alias else imp.name
            if local_alias == imported_name:
                if imp.module:
                    # from X import Y
                    target_mod = self.module_by_path.get(imp.module)
                    if target_mod:
                        # Look for symbol named imp.name in target_mod
                        for sym in target_mod.symbols:
                            if sym.name == imp.name:
                                return sym
                else:
                    # import X
                    target_mod = self.module_by_path.get(imp.name)
                    if target_mod:
                        # References the module itself
                        return None
        return None

    def resolve_call(
        self,
        call_node: ast.Call,
        caller_symbol: Symbol,
        current_module: ModuleIndex,
        local_types: Dict[str, str],
    ) -> List[Tuple[str, CallResolution]]:
        """Resolve an ast.Call node to one or more (callee_symbol_id, resolution) pairs.

        Returns:
            List of (callee_id, CallResolution). If unresolved, returns [(raw_callee, UNRESOLVED)].
        """
        func = call_node.func

        # 1. Direct Name Call: foo(...)
        if isinstance(func, ast.Name):
            callee_name = func.id

            # 1a. Recursion: function calls itself
            if caller_symbol.name == callee_name:
                return [(caller_symbol.symbol_id, CallResolution.EXACT)]

            # 1b. Local function in the same module
            local_syms = self.by_file_and_name.get((current_module.file, callee_name), [])
            for sym in local_syms:
                if sym.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION, SymbolKind.CLASS):
                    return [(sym.symbol_id, CallResolution.EXACT)]

            # 1c. Imported function or class
            imported_sym = self._resolve_import_symbol(current_module, callee_name)
            if imported_sym:
                return [(imported_sym.symbol_id, CallResolution.EXACT)]

            # 1d. Known global in repository
            global_syms = [
                s for s in self.by_name.get(callee_name, [])
                if s.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION, SymbolKind.CLASS)
            ]
            if len(global_syms) == 1:
                return [(global_syms[0].symbol_id, CallResolution.PROBABLE)]
            elif len(global_syms) > 1:
                return [(s.symbol_id, CallResolution.PROBABLE) for s in global_syms]

            # 1e. Built-in or unresolved
            return [(callee_name, CallResolution.UNRESOLVED)]

        # 2. Attribute Method Call: obj.method(...)
        elif isinstance(func, ast.Attribute):
            method_name = func.attr
            receiver = func.value

            # 2a. Self call: self.method(...)
            if isinstance(receiver, ast.Name) and receiver.id == "self":
                # Find enclosing class
                if caller_symbol.parent_symbol:
                    parent_cls = self.by_id.get(caller_symbol.parent_symbol)
                    if parent_cls:
                        target = self.by_file_and_qname.get(
                            (parent_cls.file, f"{parent_cls.name}.{method_name}")
                        )
                        if target:
                            return [(target.symbol_id, CallResolution.EXACT)]

            # 2b. Known local variable type: e.g. user_service = UserService(); user_service.get(...)
            if isinstance(receiver, ast.Name):
                var_name = receiver.id
                inferred_class_name = local_types.get(var_name)
                if inferred_class_name:
                    # Look for inferred_class_name.method_name
                    candidates: List[Symbol] = []
                    for s in self._all_symbols:
                        if s.name == method_name and s.kind in (
                            SymbolKind.METHOD,
                            SymbolKind.ASYNC_METHOD,
                        ):
                            if inferred_class_name in s.qualified_name:
                                candidates.append(s)
                    if candidates:
                        return [(candidates[0].symbol_id, CallResolution.EXACT)]

            # 2c. Direct Class attribute method: ClassName.method(...)
            if isinstance(receiver, ast.Name):
                cls_name = receiver.id
                target = self.by_file_and_qname.get(
                    (current_module.file, f"{cls_name}.{method_name}")
                )
                if target:
                    return [(target.symbol_id, CallResolution.EXACT)]
                imported_cls = self._resolve_import_symbol(current_module, cls_name)
                if imported_cls and imported_cls.kind == SymbolKind.CLASS:
                    target = self.by_file_and_qname.get(
                        (imported_cls.file, f"{imported_cls.name}.{method_name}")
                    )
                    if target:
                        return [(target.symbol_id, CallResolution.EXACT)]

            # 2d. Chained attribute (e.g. self.repo.find_by_id) or un-inferred receiver
            method_candidates = [
                s for s in self.by_name.get(method_name, [])
                if s.kind in (SymbolKind.METHOD, SymbolKind.ASYNC_METHOD)
            ]

            if len(method_candidates) == 1:
                return [(method_candidates[0].symbol_id, CallResolution.PROBABLE)]
            elif len(method_candidates) > 1:
                # Check if one of the candidate classes is imported in the current module
                imported_class_names = {
                    imp.alias if imp.alias else imp.name for imp in current_module.imports
                }
                matching_imported = [
                    s for s in method_candidates
                    if any(cls_name in s.qualified_name for cls_name in imported_class_names)
                ]
                if len(matching_imported) == 1:
                    return [(matching_imported[0].symbol_id, CallResolution.PROBABLE)]
                elif matching_imported:
                    return [(s.symbol_id, CallResolution.PROBABLE) for s in matching_imported]
                return [(s.symbol_id, CallResolution.PROBABLE) for s in method_candidates]

            # Unresolved attribute call
            call_raw = f"{ast.unparse(receiver)}.{method_name}"
            return [(call_raw, CallResolution.UNRESOLVED)]

        # 3. Dynamic or complex call (e.g. func()() or [x]()):
        raw_call = ast.unparse(func)
        return [(raw_call, CallResolution.UNRESOLVED)]
