"""Evidence validator for source-grounded investigation claims.

Validates that every EvidenceItem references:
  - a file that exists within the repository
  - a line range that is plausible (start <= end, both >= 1)
  - a symbol that can be found in the RepositoryIndex (when symbol_id is set)
  - source_text that is non-empty

Distinguishes issues by severity:
  - ERROR   — claim is definitely unsupported (file missing, line 0, etc.)
  - WARNING — claim is partially grounded (unresolved edges, empty text)
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from backend.app.ingestion.models import RepositoryIndex
from backend.app.validation.models import EvidenceItem, EvidenceKind


class ValidationIssue:
    """A single evidence validation issue."""

    def __init__(self, severity: str, evidence_id: str, message: str) -> None:
        self.severity = severity  # "ERROR" | "WARNING"
        self.evidence_id = evidence_id
        self.message = message

    def __str__(self) -> str:
        return f"[{self.severity}] evidence={self.evidence_id}: {self.message}"


class EvidenceValidator:
    """Validates EvidenceItems against a repository snapshot."""

    def __init__(self, repo_root: Path, repository_index: RepositoryIndex) -> None:
        self.repo_root = repo_root.resolve()
        self.repository_index = repository_index
        # Pre-build a set of known symbol IDs for O(1) lookups
        self._known_symbol_ids = {
            s.symbol_id for s in repository_index.all_symbols()
        }
        # Pre-build known file paths (derived from indexed symbols)
        self._known_files = {
            s.file for s in repository_index.all_symbols()
        }

    def validate(self, items: List[EvidenceItem]) -> List[ValidationIssue]:
        """Validate all evidence items and return a list of issues."""
        issues: List[ValidationIssue] = []
        for item in items:
            issues.extend(self._validate_item(item))
        return issues

    def validation_summary(self, items: List[EvidenceItem]) -> Tuple[str, List[str]]:
        """Return (grounding_label, list_of_human_readable_issue_strings).

        grounding_label:
          - 'grounded'           — no ERRORs, no or few WARNINGs
          - 'partially_grounded' — has WARNINGs but no ERRORs, or has ERRORs on
                                   UNRESOLVED evidence only
          - 'ungrounded'         — has ERRORs on DIRECT or STATIC_INFERENCE evidence
        """
        issues = self.validate(items)
        messages = [str(i) for i in issues]

        error_kinds = {
            i.severity
            for i in issues
            if i.severity == "ERROR"
        }

        # Separate errors on unresolved evidence from others
        unresolved_ids = {
            ev.evidence_id
            for ev in items
            if ev.kind == EvidenceKind.UNRESOLVED
        }
        hard_errors = [
            i
            for i in issues
            if i.severity == "ERROR" and i.evidence_id not in unresolved_ids
        ]

        if hard_errors:
            grounding = "ungrounded"
        elif error_kinds:
            grounding = "partially_grounded"
        elif any(i.severity == "WARNING" for i in issues):
            grounding = "partially_grounded"
        else:
            grounding = "grounded"

        return grounding, messages

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_item(self, item: EvidenceItem) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        eid = item.evidence_id

        # 1. File existence in repository
        if item.file not in self._known_files:
            # Check if the actual file exists on disk (may be newly added)
            disk_path = self.repo_root / item.file
            if not disk_path.is_file():
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        eid,
                        f"File '{item.file}' does not exist in repository.",
                    )
                )

        # 2. Line range plausibility
        if item.start_line < 1 or item.end_line < 1:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    eid,
                    f"Invalid line range: start={item.start_line}, end={item.end_line} (must be >= 1).",
                )
            )
        elif item.start_line > item.end_line:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    eid,
                    f"start_line ({item.start_line}) exceeds end_line ({item.end_line}).",
                )
            )

        # 3. Symbol existence when symbol_id is provided
        if item.symbol_id is not None:
            if item.symbol_id not in self._known_symbol_ids:
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        eid,
                        f"Symbol '{item.symbol_id}' was not found in the repository index.",
                    )
                )

        # 4. Source text non-empty for DIRECT evidence
        if item.kind == EvidenceKind.DIRECT and not item.source_text.strip():
            issues.append(
                ValidationIssue(
                    "WARNING",
                    eid,
                    "DIRECT evidence has empty source_text — claim may be unsupported.",
                )
            )

        # 5. UNRESOLVED evidence — informational warning
        if item.kind == EvidenceKind.UNRESOLVED:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    eid,
                    f"Evidence item references an unresolved symbol or call target.",
                )
            )

        return issues
