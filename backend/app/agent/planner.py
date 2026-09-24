"""Deterministic investigation planner.

Accepts a natural-language developer question and drives tool calls in a
structured, reproducible sequence.  No LLM involved — decisions are made by
keyword extraction and lightweight heuristics.

Strategies
----------
TRACE   : "trace", "follow", "path", "flow", "route", "request"
           → find entry points, BFS call chain, identify key nodes
EXPLAIN : "explain", "how does", "what does", "describe"
           → find target symbol, fetch source + callers + callees
FIND    : "where", "find", "locate", "which file"
           → BM25 search, symbol lookup, return matches
SEARCH  : default for any other question
           → BM25 search + symbol lookup for top hits
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.agent.models import (
    FindCalleesOutput,
    FindCallersOutput,
    GetSourceOutput,
    KeywordSearchOutput,
    SymbolLookupOutput,
    ToolResult,
)
from backend.app.agent.tools import ToolRegistry
from backend.app.validation.models import CallChainStep, EvidenceItem, EvidenceKind, ExecutionStep


# ---------------------------------------------------------------------------
# Stop words for keyword extraction
# ---------------------------------------------------------------------------

_STOP_WORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "can",
    "do", "does", "for", "from", "has", "have", "how", "i", "if", "in",
    "is", "it", "its", "me", "not", "of", "on", "or", "our", "please",
    "show", "so", "tell", "that", "the", "their", "them", "then", "there",
    "this", "to", "us", "using", "was", "we", "what", "when", "where",
    "which", "who", "why", "will", "with", "you",
}

# Heuristic role classification for symbols
_ROLE_PATTERNS: List[Tuple[str, str]] = [
    (r"endpoint|route|handler|view",             "entry_point"),
    (r"auth|verify|validate|require|check|token","auth"),
    (r"service|svc",                              "service"),
    (r"repositor|repo|find_by|update_user|fetch","repository"),
    (r"database|db|execute|query|write|connect",  "database"),
    (r"config|setting",                           "config"),
    (r"error|exception",                          "error_handler"),
]


def _detect_role(name: str) -> str:
    """Classify a symbol by its name using heuristic patterns."""
    low = name.lower()
    for pattern, role in _ROLE_PATTERNS:
        if re.search(pattern, low):
            return role
    return "general"


def _extract_keywords(question: str) -> List[str]:
    """Extract non-stop-word tokens from a question string."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", question)
    seen: Set[str] = set()
    result: List[str] = []
    for tok in tokens:
        low = tok.lower()
        if low not in _STOP_WORDS and low not in seen:
            seen.add(low)
            result.append(tok)
    return result


def _detect_intent(question: str) -> str:
    """Return 'trace' | 'explain' | 'find' | 'search'."""
    low = question.lower()
    if any(kw in low for kw in ("trace", "follow", "path", "flow", "route request", "request to")):
        return "trace"
    if any(kw in low for kw in ("explain", "how does", "what does", "describe", "how is")):
        return "explain"
    if any(kw in low for kw in ("where is", "where does", "find", "locate", "which file")):
        return "find"
    return "search"


def _summarise_result(result: ToolResult, max_len: int = 200) -> str:
    """Produce a short human-readable summary of a tool result."""
    if not result.success:
        return f"Error: {result.error}"
    data = result.data
    if data is None:
        return "No data returned."
    if isinstance(data, KeywordSearchOutput):
        names = [r.document_id for r in data.results[:3]]
        return f"Found {data.total_found} chunks. Top: {names}"
    if isinstance(data, SymbolLookupOutput):
        names = [s.symbol_id for s in data.symbols[:3]]
        return f"Found {data.total_found} symbols: {names}"
    if isinstance(data, FindCalleesOutput):
        edges = [(e.callee, e.resolution) for e in data.callees[:4]]
        return f"{data.total_found} callees: {edges}"
    if isinstance(data, FindCallersOutput):
        edges = [(e.caller, e.resolution) for e in data.callers[:4]]
        return f"{data.total_found} callers: {edges}"
    if isinstance(data, GetSourceOutput):
        preview = data.text[:100].replace("\n", "↵")
        return f"Source {data.file}:{data.start_line}-{data.end_line}: {preview!r}"
    txt = str(data)
    return txt[:max_len] + ("…" if len(txt) > max_len else "")


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class InvestigationPlanner:
    """Deterministic investigation planner driven by question intent."""

    #: Hard cap on tool invocations per investigation to keep latency bounded.
    MAX_STEPS = 20
    #: Maximum BFS call-chain depth for trace investigations.
    MAX_CHAIN_DEPTH = 5

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def investigate(
        self, question: str
    ) -> Tuple[List[ExecutionStep], List[EvidenceItem], List[CallChainStep]]:
        """Run a full deterministic investigation.

        Returns:
            (execution_steps, evidence_items, call_chain_steps)
        """
        self._steps: List[ExecutionStep] = []
        self._evidence: List[EvidenceItem] = []
        self._step_counter = 0

        intent = _detect_intent(question)
        keywords = _extract_keywords(question)

        if intent == "trace":
            call_chain = self._run_trace_strategy(question, keywords)
        elif intent == "explain":
            call_chain = self._run_explain_strategy(question, keywords)
        else:
            call_chain = self._run_search_strategy(question, keywords)

        return self._steps, self._evidence, call_chain

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _run_trace_strategy(
        self, question: str, keywords: List[str]
    ) -> List[CallChainStep]:
        """Trace: find entry points, follow call chain, collect evidence."""
        # Step 1 — keyword search to find relevant chunks
        query = " ".join(keywords[:8])
        search_result = self._call_tool(
            "keyword_search",
            {"query": query, "top_k": 8},
            reason=f"Find chunks relevant to '{question[:60]}'",
        )

        # Step 2 — identify candidate entry-point symbols from search results
        entry_point_ids: List[str] = []
        if search_result.success and isinstance(search_result.data, KeywordSearchOutput):
            for hit in search_result.data.results:
                sid = hit.symbol_id
                if not sid:
                    continue
                # Accept symbols from routes.py OR those whose name matches entry_point pattern
                from_routes = "route" in (hit.file or "").lower()
                is_ep = _detect_role(sid.split("::")[-1]) == "entry_point"
                if from_routes or is_ep:
                    entry_point_ids.append(sid)

        # Step 3 — if no entry points from search, explicitly search for routes/endpoints
        # ONLY if the initial search found hits (meaning the concept exists in the codebase)
        initial_hits = search_result.data.results if (search_result.success and isinstance(search_result.data, KeywordSearchOutput)) else []
        if not entry_point_ids and initial_hits:
            route_search = self._call_tool(
                "keyword_search",
                {"query": "route endpoint API request", "top_k": 5},
                reason="No entry points found in initial search; searching for route/endpoint symbols.",
            )
            if route_search.success and isinstance(route_search.data, KeywordSearchOutput):
                for hit in route_search.data.results:
                    sid = hit.symbol_id
                    if not sid:
                        continue
                    from_routes = "route" in (hit.file or "").lower()
                    is_ep = _detect_role(sid.split("::")[-1]) in ("entry_point", "general")
                    if from_routes or is_ep:
                        entry_point_ids.append(sid)

        # Prefer write-related entry points if question mentions "write" or "update"
        q_low = question.lower()
        prefer_write = any(w in q_low for w in ("write", "update", "create", "post", "insert"))

        if prefer_write:
            entry_point_ids.sort(
                key=lambda sid: (0 if any(w in sid.lower() for w in ("update", "write", "create")) else 1)
            )

        # Deduplicate while preserving order
        seen: Set[str] = set()
        ordered_eps: List[str] = []
        for sid in entry_point_ids:
            if sid not in seen:
                seen.add(sid)
                ordered_eps.append(sid)

        # Step 4 — symbol lookup for the best entry point if hits exist
        if not ordered_eps and initial_hits:
            # Last resort: search for any endpoint-like symbols
            lookup = self._call_tool(
                "symbol_lookup",
                {"symbol_query": "endpoint"},
                reason="No entry point identified; looking up 'endpoint' symbols.",
            )
            if lookup.success and isinstance(lookup.data, SymbolLookupOutput):
                ordered_eps = [s.symbol_id for s in lookup.data.symbols[:2]]

        if not ordered_eps:
            return []  # Cannot trace without an entry point

        # Use at most 2 entry points
        entry_points = ordered_eps[:2]

        # Step 5 — trace each entry point
        all_chains: List[List[CallChainStep]] = []
        for ep_id in entry_points:
            chain = self._trace_from(ep_id)
            if chain:
                all_chains.append(chain)
            if len(self._steps) >= self.MAX_STEPS:
                break

        if not all_chains:
            return []

        # Return the longest chain (most complete trace)
        best_chain = max(all_chains, key=len)

        # Step 6 — collect source evidence for key chain nodes
        self._collect_chain_evidence(best_chain)

        return best_chain

    def _run_explain_strategy(
        self, question: str, keywords: List[str]
    ) -> List[CallChainStep]:
        """Explain: search for target, show source, callers, callees."""
        query = " ".join(keywords[:6])
        search_result = self._call_tool(
            "keyword_search",
            {"query": query, "top_k": 5},
            reason="Search for the symbol being asked about.",
        )
        candidate_symbols: List[str] = []
        if search_result.success and isinstance(search_result.data, KeywordSearchOutput):
            for hit in search_result.data.results:
                if hit.symbol_id and hit.symbol_id not in candidate_symbols:
                    candidate_symbols.append(hit.symbol_id)

        # Symbol lookup on search hit candidates, followed by top keywords
        lookup_targets = candidate_symbols[:3] + [kw for kw in keywords[:3] if kw not in candidate_symbols]
        for target in lookup_targets:
            if len(self._steps) >= self.MAX_STEPS:
                break
            result = self._call_tool(
                "symbol_lookup",
                {"symbol_query": target},
                reason=f"Look up '{target}' as a potential symbol.",
            )
            if result.success and isinstance(result.data, SymbolLookupOutput):
                for sym in result.data.symbols[:2]:
                    self._add_symbol_evidence(
                        sym.symbol_id,
                        sym.file,
                        sym.start_line,
                        sym.end_line,
                        f"Relevant symbol found for explain query: '{sym.name}'.",
                    )
                    self._call_tool(
                        "find_callees",
                        {"symbol_id": sym.symbol_id, "limit": 5},
                        reason=f"Understand what '{sym.symbol_id}' calls.",
                    )
        return []

    def _run_search_strategy(
        self, question: str, keywords: List[str]
    ) -> List[CallChainStep]:
        """General search: BM25 + symbol lookup for top hits."""
        query = " ".join(keywords[:8])
        search_result = self._call_tool(
            "keyword_search",
            {"query": query, "top_k": 8},
            reason="BM25 search for relevant code chunks.",
        )
        if search_result.success and isinstance(search_result.data, KeywordSearchOutput):
            for hit in search_result.data.results[:3]:
                if hit.symbol_id and len(self._steps) < self.MAX_STEPS:
                    self._add_symbol_evidence(hit.symbol_id, hit.file, hit.start_line, hit.end_line, f"Chunk matched search query '{query}'.")
        return []

    # ------------------------------------------------------------------
    # BFS call-chain tracer
    # ------------------------------------------------------------------

    def _trace_from(self, entry_symbol_id: str) -> List[CallChainStep]:
        """BFS call chain starting at entry_symbol_id, up to MAX_CHAIN_DEPTH."""
        # Symbol lookup to get location for chain step 0
        lookup = self._call_tool(
            "symbol_lookup",
            {"symbol_query": entry_symbol_id},
            reason=f"Resolve entry point symbol '{entry_symbol_id}'.",
        )
        if not lookup.success or not isinstance(lookup.data, SymbolLookupOutput) or not lookup.data.symbols:
            return []

        entry_sym = lookup.data.symbols[0]
        chain: List[CallChainStep] = [
            CallChainStep(
                order=0,
                symbol_id=entry_sym.symbol_id,
                symbol_name=entry_sym.name,
                qualified_name=entry_sym.qualified_name,
                file=entry_sym.file,
                start_line=entry_sym.start_line,
                end_line=entry_sym.end_line,
                role=_detect_role(entry_sym.name),
                edge_resolution=None,
            )
        ]

        current_id = entry_sym.symbol_id
        visited: Set[str] = {current_id}
        depth = 0

        while depth < self.MAX_CHAIN_DEPTH and len(self._steps) < self.MAX_STEPS:
            callee_result = self._call_tool(
                "find_callees",
                {"symbol_id": current_id, "limit": 10},
                reason=f"Follow call chain from '{current_id}' (depth {depth + 1}).",
            )
            if not callee_result.success or not isinstance(callee_result.data, FindCalleesOutput):
                break

            # Pick the best next callee: prefer resolved, avoid unresolved, avoid already-visited
            callees = callee_result.data.callees
            if not callees:
                break

            # Filter out visited and unresolved-only
            resolved = [e for e in callees if e.resolution != "unresolved" and e.callee not in visited]
            unresolved_only = [e for e in callees if e.resolution == "unresolved" and e.callee not in visited]

            # Prefer method/function callees over class callees.
            # A class callee (e.g. "UserService") typically has no outgoing calls in the
            # call graph — the actual interesting target is the method (e.g. "UserService.update_status").
            # Heuristic: if the callee has no "::" *after* the first "::" separator it's likely a
            # class-only reference.  We deprioritize those in favour of qualified "Class.method" targets.
            def _is_class_only(callee_id: str) -> bool:
                parts = callee_id.split("::")
                # e.g. "app/services/users.py::UserService" → 2 parts, last has no dot → class
                if len(parts) >= 2:
                    name = parts[-1]
                    return "." not in name and name[0].isupper()
                return False

            method_resolved = [e for e in resolved if not _is_class_only(e.callee)]
            if not method_resolved and resolved:
                # Fall back to all resolved if no method candidates exist
                method_resolved = resolved

            next_edge = None
            if method_resolved:
                # Among resolved methods/functions, prioritize by role importance:
                # database > repository > service > auth > general > class
                role_priority = {"database": 0, "repository": 1, "service": 2, "auth": 3, "general": 4}
                resolved_sorted = sorted(
                    method_resolved,
                    key=lambda e: role_priority.get(_detect_role(e.callee.split("::")[-1]), 5),
                )
                next_edge = resolved_sorted[0]
            elif unresolved_only:
                next_edge = unresolved_only[0]

            if next_edge is None:
                break

            # Look up the callee symbol for location details
            callee_lookup = self._call_tool(
                "symbol_lookup",
                {"symbol_query": next_edge.callee},
                reason=f"Resolve callee '{next_edge.callee}' for chain step {len(chain)}.",
            )

            if callee_lookup.success and isinstance(callee_lookup.data, SymbolLookupOutput) and callee_lookup.data.symbols:
                callee_sym = callee_lookup.data.symbols[0]
                chain.append(
                    CallChainStep(
                        order=len(chain),
                        symbol_id=callee_sym.symbol_id,
                        symbol_name=callee_sym.name,
                        qualified_name=callee_sym.qualified_name,
                        file=callee_sym.file,
                        start_line=callee_sym.start_line,
                        end_line=callee_sym.end_line,
                        role=_detect_role(callee_sym.name),
                        edge_resolution=next_edge.resolution,
                    )
                )
                visited.add(callee_sym.symbol_id)
                current_id = callee_sym.symbol_id
            else:
                # Callee not resolved — add best-effort step
                callee_name = next_edge.callee.split("::")[-1]
                chain.append(
                    CallChainStep(
                        order=len(chain),
                        symbol_id=next_edge.callee,
                        symbol_name=callee_name,
                        qualified_name=next_edge.callee,
                        file=next_edge.file,
                        start_line=next_edge.line,
                        end_line=next_edge.line,
                        role=_detect_role(callee_name),
                        edge_resolution=next_edge.resolution,
                    )
                )
                visited.add(next_edge.callee)
                current_id = next_edge.callee

            depth += 1

            # Stop once we hit a database node (we've reached the end of the chain)
            if chain and chain[-1].role == "database":
                break

        return chain

    # ------------------------------------------------------------------
    # Evidence collection
    # ------------------------------------------------------------------

    def _collect_chain_evidence(self, chain: List[CallChainStep]) -> None:
        """Fetch source for notable chain nodes and add evidence items."""
        for step in chain:
            if len(self._steps) >= self.MAX_STEPS:
                break
            self._add_symbol_evidence(
                step.symbol_id,
                step.file,
                step.start_line,
                step.end_line,
                f"Call chain node: {step.role} — '{step.symbol_name}'",
            )

    def _add_symbol_evidence(
        self,
        symbol_id: str,
        file: str,
        start_line: int,
        end_line: int,
        description: str,
        kind: EvidenceKind = EvidenceKind.DIRECT,
    ) -> None:
        """Fetch source text and add an EvidenceItem for the given symbol."""
        source_result = self._call_tool(
            "get_source",
            {"file": file, "start_line": start_line, "end_line": end_line},
            reason=f"Retrieve source for evidence: {description[:60]}",
        )
        source_text = ""
        if source_result.success and isinstance(source_result.data, GetSourceOutput):
            source_text = source_result.data.text
        elif kind == EvidenceKind.DIRECT:
            kind = EvidenceKind.STATIC_INFERENCE  # downgrade if source unavailable

        sym_name = symbol_id.split("::")[-1] if "::" in symbol_id else symbol_id
        self._evidence.append(
            EvidenceItem(
                kind=kind,
                file=file,
                start_line=start_line,
                end_line=end_line,
                symbol_id=symbol_id,
                symbol_name=sym_name,
                source_text=source_text,
                description=description,
            )
        )

    # ------------------------------------------------------------------
    # Tool call wrapper with step tracking
    # ------------------------------------------------------------------

    def _call_tool(
        self, tool_name: str, params: Dict[str, Any], reason: str
    ) -> ToolResult:
        """Execute a tool and record the invocation in the trace."""
        if self._step_counter >= self.MAX_STEPS:
            from backend.app.agent.models import ToolResult as TR
            return TR(success=False, tool_name=tool_name, error="Step limit reached.")

        self._step_counter += 1
        t0 = time.perf_counter()
        result = self.registry.execute(tool_name, params)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        self._steps.append(
            ExecutionStep(
                step_number=self._step_counter,
                tool_name=tool_name,
                input_params=params,
                output_summary=_summarise_result(result),
                reason=reason,
                duration_ms=round(duration_ms, 3),
            )
        )
        return result
