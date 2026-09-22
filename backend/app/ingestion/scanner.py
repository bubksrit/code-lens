"""Repository scanner.

Walks a repository root, discovers Python source files, and delegates
per-file symbol extraction to ``python_parser.extract_symbols``.

Excluded paths (never traversed):
  .git  __pycache__  *.egg-info  dist  build  .venv  venv  env  .tox  .nox
  node_modules  *.pyc  *.pyo

Usage::

    from backend.app.ingestion.scanner import scan_repository
    index = scan_repository("/path/to/repo")
    print(len(index.all_symbols()), "symbols found")
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Set

from backend.app.ingestion.models import (
    ModuleIndex,
    ParseDiagnostic,
    RepositoryIndex,
    Symbol,
)
from backend.app.ingestion.python_parser import extract_symbols

# ---------------------------------------------------------------------------
# Directory / file exclusion rules
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS: Set[str] = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "ENV",
    ".env",
    "dist",
    "build",
    "node_modules",
    "site-packages",
    ".eggs",
}

_EXCLUDED_SUFFIXES: Set[str] = {".pyc", ".pyo", ".pyd"}


def _is_excluded_dir(name: str) -> bool:
    """Return True if the directory name should never be traversed."""
    return name in _EXCLUDED_DIRS or name.endswith(".egg-info")


def _discover_python_files(root: Path) -> List[Path]:
    """Yield all .py files under *root* excluding ignored directories."""
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Prune excluded dirs in-place so os.walk does not descend into them
        dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d)]
        for filename in filenames:
            if filename.endswith(".py") and not filename.endswith(tuple(_EXCLUDED_SUFFIXES)):
                found.append(Path(dirpath) / filename)
    return sorted(found)  # deterministic order


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_repository(
    root: str,
    encoding: str = "utf-8",
) -> RepositoryIndex:
    """Scan the repository at *root* and return a :class:`RepositoryIndex`.

    Every Python file is parsed for symbols.  Files that contain syntax errors
    or encoding problems are captured as diagnostics; the scan continues for
    all other files.

    Args:
        root: Absolute or relative path to the repository root directory.
        encoding: Source file encoding to assume (default ``"utf-8"``).

    Returns:
        A :class:`RepositoryIndex` with all extracted symbols and any
        per-file diagnostics.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError(f"Repository root does not exist or is not a directory: {root!r}")

    py_files = _discover_python_files(root_path)

    modules: List[ModuleIndex] = []
    repo_diagnostics: List[ParseDiagnostic] = []

    for abs_path in py_files:
        relative = abs_path.relative_to(root_path).as_posix()
        try:
            source = abs_path.read_text(encoding=encoding, errors="replace")
        except OSError as exc:
            repo_diagnostics.append(ParseDiagnostic(
                file=relative,
                message=f"Could not read file: {exc}",
            ))
            continue

        module_idx = extract_symbols(source, relative)
        modules.append(module_idx)

    return RepositoryIndex(
        root=str(root_path),
        modules=modules,
        diagnostics=repo_diagnostics,
    )


def find_symbol(index: RepositoryIndex, symbol_id: str) -> Optional[Symbol]:
    """Return the symbol with the given *symbol_id*, or ``None``."""
    return index.find_symbol(symbol_id)


def find_symbols_by_name(index: RepositoryIndex, name: str) -> List[Symbol]:
    """Return all symbols whose simple name matches *name* (case-sensitive)."""
    return index.find_symbols_by_name(name)


def find_symbols_by_file(index: RepositoryIndex, relative_file: str) -> List[Symbol]:
    """Return all symbols declared in *relative_file* (relative to repo root)."""
    return index.find_symbols_by_file(relative_file)
