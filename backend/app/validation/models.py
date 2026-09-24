"""Typed schemas for the evidence layer, investigation traces, and API contracts.

Every factual claim produced by the investigation planner must be backed by an
EvidenceItem with:
  - a traceable source (file + line range)
  - an explicit certainty label (direct / static_inference / unresolved)
  - the actual source text used to support the claim
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Evidence certainty levels
# ---------------------------------------------------------------------------


class EvidenceKind(str, Enum):
    """Explicit certainty labels for every investigation claim."""

    DIRECT = "direct"
    """Claim is backed by exact source text retrieved from the repository."""

    STATIC_INFERENCE = "static_inference"
    """Claim is inferred from static analysis (call graph, AST structure)."""

    UNRESOLVED = "unresolved"
    """Claim involves a call target or symbol that could not be resolved."""


# ---------------------------------------------------------------------------
# Evidence item
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single piece of source-grounded evidence supporting an investigation claim."""

    evidence_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())[:12],
        description="Short unique identifier for this evidence item.",
    )
    kind: EvidenceKind = Field(description="Certainty label for this evidence.")
    file: str = Field(description="Repository-relative path of the evidence source.")
    start_line: int = Field(ge=1, description="1-based starting source line.")
    end_line: int = Field(ge=1, description="1-based ending source line.")
    symbol_id: Optional[str] = Field(
        default=None, description="symbol_id of the referenced symbol, if applicable."
    )
    symbol_name: Optional[str] = Field(
        default=None, description="Human-readable symbol name."
    )
    source_text: str = Field(
        description="Exact source text from the repository supporting this claim."
    )
    description: str = Field(description="Human-readable explanation of this evidence.")


# ---------------------------------------------------------------------------
# Call-chain step
# ---------------------------------------------------------------------------


class CallChainStep(BaseModel):
    """One node in a traced call chain, with source location."""

    order: int = Field(description="Position in the chain, 0-indexed.")
    symbol_id: str = Field(description="Unique symbol identifier.")
    symbol_name: str = Field(description="Short symbol name (function or method).")
    qualified_name: str = Field(description="Fully qualified name within its module.")
    file: str = Field(description="Repository-relative source file.")
    start_line: int = Field(description="1-based start line of the symbol definition.")
    end_line: int = Field(description="1-based end line of the symbol definition.")
    role: str = Field(
        description="Functional role in the chain, e.g. 'entry_point', 'auth', 'service', 'repository', 'database'."
    )
    edge_resolution: Optional[str] = Field(
        default=None,
        description="How the preceding call was resolved: 'exact' | 'probable' | 'unresolved' | None (for first node).",
    )


# ---------------------------------------------------------------------------
# Agent execution step (investigation trace)
# ---------------------------------------------------------------------------


class ExecutionStep(BaseModel):
    """One tool invocation in the deterministic investigation planner's trace."""

    step_number: int = Field(description="Sequential 1-based step index.")
    tool_name: str = Field(description="Name of the tool that was invoked.")
    input_params: Dict[str, Any] = Field(description="Arguments passed to the tool.")
    output_summary: str = Field(
        description="Short human-readable summary of the tool's output."
    )
    reason: str = Field(description="Why the planner chose to call this tool at this step.")
    duration_ms: float = Field(description="Wall-clock duration of the tool call in milliseconds.")


# ---------------------------------------------------------------------------
# API request and response
# ---------------------------------------------------------------------------


class InvestigationRequest(BaseModel):
    """Public API input for a code investigation query."""

    repository_id: str = Field(
        description="Registered repository identifier (e.g. 'demo_repo').",
        min_length=1,
    )
    question: str = Field(
        description="Natural-language developer question about the codebase.",
        min_length=5,
    )


class InvestigationResult(BaseModel):
    """Complete result of a deterministic code investigation."""

    investigation_id: str = Field(description="Unique ID for this investigation run.")
    repository_id: str = Field(description="Repository that was investigated.")
    question: str = Field(description="The original developer question.")

    answer_summary: str = Field(
        description="Template-based, source-grounded answer to the question."
    )

    call_chain: List[CallChainStep] = Field(
        default_factory=list,
        description="Ordered nodes in the primary call chain identified.",
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Source-grounded evidence items supporting the answer.",
    )
    trace: List[ExecutionStep] = Field(
        default_factory=list,
        description="Full investigation execution trace (one entry per tool call).",
    )
    validation_issues: List[str] = Field(
        default_factory=list,
        description="Any validation warnings (unsupported claims, unresolved symbols).",
    )

    total_steps: int = Field(description="Total number of tool invocations performed.")
    latency_ms: float = Field(description="Total wall-clock latency in milliseconds.")
    grounding: str = Field(
        description="'grounded' | 'partially_grounded' | 'ungrounded' based on evidence certainty."
    )
