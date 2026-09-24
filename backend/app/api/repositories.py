"""Repository registry — maps repository_id strings to filesystem paths and metadata.

The public investigation API accepts a ``repository_id`` (e.g. ``"demo_repo"``)
rather than arbitrary filesystem paths. This module resolves IDs to validated
absolute paths, maintains repository metadata for the frontend, and provides
a cached ToolRegistry per repository.

Filesystem paths are resolved relative to the project root detected at import
time, or directly if provided as absolute paths. Additional repositories can
be registered dynamically without altering investigation logic or UI code.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.agent.tools import ToolRegistry, create_tool_registry

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_PROJECT_ROOT: Optional[Path] = None
for _parent in _HERE.parents:
    if (_parent / "pyproject.toml").is_file():
        _PROJECT_ROOT = _parent
        break

if _PROJECT_ROOT is None:
    raise RuntimeError(
        "Cannot locate project root (no pyproject.toml found in parent directories)."
    )


# ---------------------------------------------------------------------------
# Repository Metadata Model
# ---------------------------------------------------------------------------

class RepositoryMetadata(BaseModel):
    """Metadata describing an indexed repository available for investigation."""

    id: str = Field(description="Unique string identifier (e.g. 'demo_repo').")
    name: str = Field(description="Human-friendly display name for dropdowns.")
    description: str = Field(description="Brief explanation of the repository content.")
    path: str = Field(description="Filesystem path relative to project root or absolute.")


# ---------------------------------------------------------------------------
# Registry State & Management
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()

_DEFAULT_REPOSITORIES: Dict[str, RepositoryMetadata] = {
    "demo_ecommerce": RepositoryMetadata(
        id="demo_ecommerce",
        name="E-Commerce API",
        description="Handles product listings, customer orders, stock validation, and order persistence.",
        path="data/demo_ecommerce",
    ),
    "demo_auth": RepositoryMetadata(
        id="demo_auth",
        name="Authentication Service",
        description="Handles user login, credential verification, token issuance, and session management.",
        path="data/demo_auth",
    ),
    "demo_tasks": RepositoryMetadata(
        id="demo_tasks",
        name="Task Management API",
        description="Handles task creation, validation, retrieval, and status tracking.",
        path="data/demo_tasks",
    ),
    "demo_repo": RepositoryMetadata(
        id="demo_repo",
        name="Multi-Layer Python App",
        description="Multi-layer Python app demonstrating API routes, auth, services, repositories, and database operations.",
        path="data/demo_repo",
    ),
}

_REPO_REGISTRY: Dict[str, RepositoryMetadata] = dict(_DEFAULT_REPOSITORIES)


def resolve_repository_path(repository_id: str) -> Path:
    """Return the validated absolute path for a repository_id.

    Raises:
        ValueError: If the repository_id is not registered.
        FileNotFoundError: If the registered path does not exist on disk.
    """
    with _registry_lock:
        entry = _REPO_REGISTRY.get(repository_id)
        if entry is None:
            valid = sorted(_REPO_REGISTRY.keys())
            raise ValueError(
                f"Unknown repository_id '{repository_id}'. "
                f"Valid identifiers: {valid}."
            )
        raw_path = Path(entry.path)

    if raw_path.is_absolute():
        abs_path = raw_path.resolve()
    else:
        abs_path = (_PROJECT_ROOT / raw_path).resolve()

    if not abs_path.is_dir():
        raise FileNotFoundError(
            f"Repository directory for '{repository_id}' does not exist at '{abs_path}'."
        )
    return abs_path


def register_repository(
    repository_id: str,
    path: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> RepositoryMetadata:
    """Register a new repository so it can be indexed and investigated.

    Args:
        repository_id: Unique string identifier for the repository.
        path: Path relative to project root, or absolute filesystem path.
        name: Optional display name for the UI (defaults to repository_id).
        description: Optional brief description of the codebase.

    Returns:
        The registered RepositoryMetadata.

    Raises:
        FileNotFoundError: If the specified directory does not exist.
        ValueError: If the repository_id is invalid.
    """
    clean_id = repository_id.strip()
    if not clean_id:
        raise ValueError("repository_id cannot be empty.")

    raw_path = Path(path.strip())
    if raw_path.is_absolute():
        abs_path = raw_path.resolve()
    else:
        abs_path = (_PROJECT_ROOT / raw_path).resolve()

    if not abs_path.is_dir():
        raise FileNotFoundError(
            f"Repository path '{path}' does not exist as a directory (resolved to '{abs_path}')."
        )

    meta = RepositoryMetadata(
        id=clean_id,
        name=name.strip() if name and name.strip() else clean_id,
        description=description.strip() if description and description.strip() else f"Repository located at {path}",
        path=path.strip(),
    )

    with _registry_lock:
        _REPO_REGISTRY[clean_id] = meta

    # Invalidate cache for this repo in case it was previously loaded
    invalidate_cache(clean_id)
    return meta


def unregister_repository(repository_id: str) -> bool:
    """Remove a repository from the registry and evict its cached index.

    Returns:
        True if the repository was removed, False if it was not found.
    """
    with _registry_lock:
        removed = _REPO_REGISTRY.pop(repository_id, None) is not None

    if removed:
        invalidate_cache(repository_id)
    return removed


def list_repositories() -> Dict[str, RepositoryMetadata]:
    """Return all registered repositories with their metadata."""
    with _registry_lock:
        return dict(_REPO_REGISTRY)


def get_repository_metadata(repository_id: str) -> Optional[RepositoryMetadata]:
    """Retrieve metadata for a specific repository if registered."""
    with _registry_lock:
        return _REPO_REGISTRY.get(repository_id)


# ---------------------------------------------------------------------------
# Per-repository ToolRegistry cache
# ---------------------------------------------------------------------------

_registry_cache: Dict[str, ToolRegistry] = {}
_cache_lock = threading.Lock()


def get_tool_registry(repository_id: str) -> ToolRegistry:
    """Return (or build and cache) a ToolRegistry for the given repository_id.

    Building the registry scans the repository, extracts AST symbols, builds
    the BM25 index, and constructs the static call graph. This is done once
    per server process per repository and cached for subsequent requests.

    Raises:
        ValueError: If the repository_id is not registered.
        FileNotFoundError: If the repository path does not exist.
    """
    with _cache_lock:
        if repository_id not in _registry_cache:
            repo_path = resolve_repository_path(repository_id)
            _registry_cache[repository_id] = create_tool_registry(repo_path)
        return _registry_cache[repository_id]


def invalidate_cache(repository_id: Optional[str] = None) -> None:
    """Evict one or all cached ToolRegistry instances.

    Args:
        repository_id: Specific repo to evict, or None to evict all.
    """
    with _cache_lock:
        if repository_id is None:
            _registry_cache.clear()
        else:
            _registry_cache.pop(repository_id, None)
