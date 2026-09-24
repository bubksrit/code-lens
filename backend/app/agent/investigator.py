"""End-to-end investigation orchestrator.

Ties together the deterministic planner, evidence validator, and
answer-template renderer to produce an InvestigationResult.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import List, Optional

from backend.app.agent.planner import InvestigationPlanner, _detect_role
from backend.app.agent.tools import ToolRegistry
from backend.app.validation.models import (
    CallChainStep,
    EvidenceItem,
    ExecutionStep,
    InvestigationResult,
)
from backend.app.validation.validator import EvidenceValidator


# ---------------------------------------------------------------------------
# Answer template generator
# ---------------------------------------------------------------------------


def _build_answer_summary(
    repository_id: str,
    question: str,
    call_chain: List[CallChainStep],
    evidence: List[EvidenceItem],
) -> str:
    """Produce a deterministic, template-based answer narrative."""
    lines: List[str] = []

    # Opening with explicit repository and question identification
    lines.append(f"**Repository:** `{repository_id}`")
    lines.append(f"**Question:** {question}\n")

    if not call_chain:
        lines.append("No clear call chain could be traced from the available symbols.")
        lines.append("See the evidence items and execution trace below for partial findings.")
        return "\n".join(lines)

    # Call chain narrative
    chain_len = len(call_chain)
    files = sorted({step.file for step in call_chain})
    lines.append(
        f"The request flows through **{chain_len} symbols** across **{len(files)} file(s)**.\n"
    )

    # Format the chain
    lines.append("**Call chain:**")
    for step in call_chain:
        arrow = "  →  " if step.order > 0 else ""
        resolution = f" _(edge: {step.edge_resolution})_" if step.edge_resolution and step.edge_resolution != "exact" else ""
        lines.append(
            f"{arrow}`{step.symbol_name}` — **{step.role}** "
            f"([`{step.file}:{step.start_line}`]){resolution}"
        )

    lines.append("")

    # Identify validation nodes
    auth_steps = [s for s in call_chain if s.role == "auth"]
    if auth_steps:
        lines.append("**Validation / authentication identified at:**")
        for s in auth_steps:
            lines.append(f"  - `{s.symbol_name}` in `{s.file}:{s.start_line}-{s.end_line}`")
        lines.append("")

    # Identify database nodes
    db_steps = [s for s in call_chain if s.role == "database"]
    if db_steps:
        action_word = "database write" if any("write" in s.symbol_name.lower() for s in db_steps) else "database operation"
        lines.append(f"**{action_word.capitalize()} identified at:**")
        for s in db_steps:
            lines.append(f"  - `{s.symbol_name}` in `{s.file}:{s.start_line}-{s.end_line}`")
        lines.append("")

    # Evidence summary
    direct_count = sum(1 for e in evidence if e.kind.value == "direct")
    inferred_count = sum(1 for e in evidence if e.kind.value == "static_inference")
    unresolved_count = sum(1 for e in evidence if e.kind.value == "unresolved")
    lines.append(
        f"**Evidence:** {direct_count} direct · {inferred_count} inferred · {unresolved_count} unresolved"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Investigator
# ---------------------------------------------------------------------------


class Investigator:
    """Orchestrates the full investigation pipeline for a repository."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        ctx = registry.context
        self._validator = EvidenceValidator(
            repo_root=ctx.repo_root,
            repository_index=ctx.repository_index,
        )

    def investigate(self, repository_id: str, question: str) -> InvestigationResult:
        """Run a complete investigation and return a structured result."""
        investigation_id = str(uuid.uuid4())
        t_start = time.perf_counter()

        planner = InvestigationPlanner(self.registry)
        steps, evidence, call_chain = planner.investigate(question)

        # Validate evidence
        grounding, validation_messages = self._validator.validation_summary(evidence)

        # Generate answer
        answer_summary = _build_answer_summary(repository_id, question, call_chain, evidence)

        latency_ms = round((time.perf_counter() - t_start) * 1000.0, 2)

        return InvestigationResult(
            investigation_id=investigation_id,
            repository_id=repository_id,
            question=question,
            answer_summary=answer_summary,
            call_chain=call_chain,
            evidence=evidence,
            trace=steps,
            validation_issues=validation_messages,
            total_steps=len(steps),
            latency_ms=latency_ms,
            grounding=grounding,
        )
