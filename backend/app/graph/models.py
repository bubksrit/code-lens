"""Data models for static call graph analysis.

Edges represent function and method invocations with explicit certainty:
- exact: unambiguous local function, imported symbol, or typed method call
- probable: method resolution across repository candidates when receiver type is inferred
- unresolved: dynamic, external, or unknown target
"""
from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Dict, Iterator, List, Optional, Set

from pydantic import BaseModel, Field


class CallResolution(str, Enum):
    EXACT = "exact"
    PROBABLE = "probable"
    UNRESOLVED = "unresolved"


class CallEdge(BaseModel):
    """A directed edge in the static call graph from caller to callee."""

    caller: str = Field(description="symbol_id of calling function, method, or module.")
    callee: str = Field(description="symbol_id of called symbol, or raw target if unresolved.")
    file: str = Field(description="Relative path of file containing the call site.")
    line: int = Field(description="1-based source line number of call site.")
    resolution: str = Field(
        description="Certainty label: 'exact' | 'probable' | 'unresolved'.",
    )
    call_expr: Optional[str] = Field(
        default=None,
        description="Original call expression text from AST unparse.",
    )

    model_config = {"frozen": True}


class CallGraph(BaseModel):
    """Complete directed static call graph for a repository."""

    edges: List[CallEdge] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.edges)

    def __iter__(self) -> Iterator[CallEdge]:
        return iter(self.edges)

    def find_callees(self, symbol_id: str) -> List[CallEdge]:
        """Return all outgoing call edges originating from symbol_id."""
        return [e for e in self.edges if e.caller == symbol_id]

    def find_callers(self, symbol_id: str) -> List[CallEdge]:
        """Return all incoming call edges targeting symbol_id."""
        return [e for e in self.edges if e.callee == symbol_id]

    def find_path(
        self,
        source_symbol: str,
        target_symbol: str,
        include_unresolved: bool = False,
    ) -> Optional[List[CallEdge]]:
        """Find the shortest path from source_symbol to target_symbol via BFS.

        Returns:
            List of CallEdge objects forming the path, or None if no path exists.
        """
        if source_symbol == target_symbol:
            return []

        # Adjacency map: node -> list of (neighbor_node, edge)
        adj: Dict[str, List[CallEdge]] = {}
        for edge in self.edges:
            if not include_unresolved and edge.resolution == CallResolution.UNRESOLVED.value:
                continue
            if edge.caller not in adj:
                adj[edge.caller] = []
            adj[edge.caller].append(edge)

        # BFS queue storing (current_node, path_of_edges)
        queue: deque[tuple[str, List[CallEdge]]] = deque([(source_symbol, [])])
        visited: Set[str] = {source_symbol}

        while queue:
            current, path = queue.popleft()
            if current == target_symbol:
                return path

            for edge in adj.get(current, []):
                next_node = edge.callee
                if next_node not in visited:
                    visited.add(next_node)
                    queue.append((next_node, path + [edge]))

        return None

    model_config = {"frozen": False}
