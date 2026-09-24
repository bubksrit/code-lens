"""API routes for repository registration, code investigation, and simulation."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.agent.investigator import Investigator
from backend.app.agent.simulation import (
    SimulationRunResult,
    SimulationTestCase,
    get_test_cases_for_repo,
    run_simulation,
)
from backend.app.api.repositories import (
    RepositoryMetadata,
    get_tool_registry,
    list_repositories,
    register_repository,
)
from backend.app.validation.models import InvestigationRequest, InvestigationResult

router = APIRouter(prefix="/api", tags=["investigate"])


class RegisterRepositoryRequest(BaseModel):
    """Payload for registering a repository for indexing and investigation."""

    repository_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique string identifier for the repository (e.g. 'demo_repo', 'my_service').",
    )
    path: str = Field(
        ...,
        min_length=1,
        description="Filesystem path relative to project root, or absolute filesystem path.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-friendly label to display in the UI dropdown.",
    )
    description: Optional[str] = Field(
        default=None,
        description="Short description of the codebase purpose and architecture.",
    )


class RepositoriesResponse(BaseModel):
    """Response containing registered repository IDs and rich metadata items."""

    repositories: List[str]
    items: List[RepositoryMetadata]


class SimulationRequest(BaseModel):
    """Request payload for running simulation test cases."""

    repository_id: str = Field(
        default="demo_repo",
        min_length=1,
        description="Target registered repository to evaluate.",
    )


@router.get(
    "/repositories",
    response_model=RepositoriesResponse,
    summary="List all registered repositories available to Code Lens.",
)
def get_repositories() -> RepositoriesResponse:
    """List all registered repository IDs along with detailed metadata for UI dropdowns."""
    repos = list_repositories()
    return RepositoriesResponse(
        repositories=list(repos.keys()),
        items=list(repos.values()),
    )


@router.post(
    "/repositories",
    response_model=RepositoryMetadata,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new repository with Code Lens.",
)
def add_repository(request: RegisterRepositoryRequest) -> RepositoryMetadata:
    """Dynamically register a new repository so Code Lens can investigate it."""
    try:
        entry = register_repository(
            repository_id=request.repository_id,
            path=request.path,
            name=request.name,
            description=request.description,
        )
        return entry
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/investigate",
    response_model=InvestigationResult,
    status_code=status.HTTP_200_OK,
    summary="Investigate a code repository with a natural-language question.",
)
def investigate(request: InvestigationRequest) -> InvestigationResult:
    """Run a deterministic agentic investigation over the specified repository.

    - Validates ``repository_id`` against the registered repository list.
    - Resolves the repository sandbox path and builds/retrieves cached indices.
    - Parses question intent, drives multi-tool investigation, and collects evidence.
    - Returns structured answer, call chain, evidence citations, and execution trace.
    """
    # 1. Resolve repository_id to a tool registry (cached per process)
    try:
        registry = get_tool_registry(request.repository_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # 2. Run investigation
    investigator = Investigator(registry=registry)
    try:
        result = investigator.investigate(
            repository_id=request.repository_id,
            question=request.question,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Investigation failed: {exc}",
        )

    return result


@router.get(
    "/simulate/cases",
    response_model=List[SimulationTestCase],
    summary="List predefined simulation test cases for a repository.",
)
def list_simulation_cases(repository_id: str = "demo_repo") -> List[SimulationTestCase]:
    """Retrieve predefined simulation test cases available for the given repository."""
    return get_test_cases_for_repo(repository_id)


@router.post(
    "/simulate",
    response_model=SimulationRunResult,
    status_code=status.HTTP_200_OK,
    summary="Execute predefined simulation benchmark test cases against a repository.",
)
def simulate(request: SimulationRequest) -> SimulationRunResult:
    """Run the predefined suite of investigation scenarios against the target repository."""
    try:
        return run_simulation(request.repository_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {exc}",
        )
