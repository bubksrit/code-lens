"""Data models for the ingestion layer.

Every symbol extracted from the repository carries exact source location
information derived from Python's AST node attributes.  Locations are
*never* computed or guessed; if the AST does not provide a value the field
is left as None and callers must treat it as unknown.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    ASYNC_FUNCTION = "async_function"
    ASYNC_METHOD = "async_method"


class ImportedName(BaseModel):
    """A single name brought into scope by an import statement."""

    module: Optional[str] = None        # e.g. "app.auth" for "from app.auth import ..."
    name: str                           # the local alias / imported name
    alias: Optional[str] = None         # present only when "as <alias>" is used
    line: int

    model_config = {"frozen": True}


class ParseDiagnostic(BaseModel):
    """A non-fatal problem encountered while parsing a file."""

    file: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None

    model_config = {"frozen": True}


class Symbol(BaseModel):
    """Complete information about one extractable Python symbol."""

    symbol_id: str = Field(
        description="Stable unique identifier: '<file>:<qualified_name>'",
    )
    name: str = Field(description="Simple (unqualified) name of the symbol.")
    qualified_name: str = Field(
        description="Dot-separated path within the module, e.g. 'MyClass.my_method'.",
    )
    kind: SymbolKind
    file: str = Field(description="Path relative to the repository root.")
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    parent_symbol: Optional[str] = Field(
        default=None,
        description="symbol_id of the enclosing symbol, or None for top-level.",
    )
    signature: str = Field(description="Function/class header as written in source.")
    docstring: Optional[str] = Field(
        default=None,
        description="First string literal in the body, or None.",
    )
    decorators: List[str] = Field(
        default_factory=list,
        description="Decorator expressions as they appear in source.",
    )
    is_async: bool = False

    model_config = {"frozen": True}


class ModuleIndex(BaseModel):
    """All symbols extracted from a single Python source file."""

    file: str
    symbols: List[Symbol] = Field(default_factory=list)
    imports: List[ImportedName] = Field(default_factory=list)
    module_docstring: Optional[str] = None
    diagnostics: List[ParseDiagnostic] = Field(default_factory=list)

    model_config = {"frozen": True}


class RepositoryIndex(BaseModel):
    """Complete symbol index for a scanned repository."""

    root: str = Field(description="Absolute path to the repository root.")
    modules: List[ModuleIndex] = Field(default_factory=list)
    diagnostics: List[ParseDiagnostic] = Field(default_factory=list)

    # Convenience aggregates ---------------------------------------------------

    def all_symbols(self) -> List[Symbol]:
        return [s for m in self.modules for s in m.symbols]

    def find_symbol(self, symbol_id: str) -> Optional[Symbol]:
        """Return the symbol with the given symbol_id, or None."""
        for sym in self.all_symbols():
            if sym.symbol_id == symbol_id:
                return sym
        return None

    def find_symbols_by_name(self, name: str) -> List[Symbol]:
        """Return all symbols whose simple name matches *name* (case-sensitive)."""
        return [s for s in self.all_symbols() if s.name == name]

    def find_symbols_by_file(self, relative_file: str) -> List[Symbol]:
        """Return all symbols declared in *relative_file*."""
        return [s for s in self.all_symbols() if s.file == relative_file]

    model_config = {"frozen": False}
