"""
Tool-integration abstraction layer.

Centralizes all "tool-style" capabilities so the backend can cleanly
connect to modern agent stacks (Responses API, Claude tool_use,
file search, web search, future sandbox execution).

No existing model layer is rewritten.  This module wraps existing
provider and retrieval capabilities as callable tool definitions that
conform to the tool_use schema pattern.

Key abstractions
----------------
ToolDefinition  : schema-compatible tool description
ToolResult      : normalized tool execution output
ToolRegistry    : registry of available tools
tool_registry   : default singleton

Usage (standalone)::

    tool = tool_registry.get("web_search")
    result = tool_registry.call("web_search", {"query": "Apple earnings"})
    print(result.content)

Usage (agent integration)::

    tool_schemas = tool_registry.to_tool_schemas()
    # Pass tool_schemas to an LLM that supports tool_use.
    # When the model returns a tool_use block, route it:
    result = tool_registry.dispatch(tool_name, tool_input)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """Schema-compatible description of a callable tool.

    Compatible with Anthropic tool_use, OpenAI function_calling, and
    the Responses API tool schema pattern.

    Attributes
    ----------
    name            : tool identifier (must be unique in registry)
    description     : what the tool does (used in LLM tool schema)
    input_schema    : JSON Schema for the tool's input parameters
    categories      : semantic categories (e.g. "retrieval", "financial")
    requires_key    : whether an API key is needed
    enabled         : whether the tool is currently active
    handler         : callable that executes the tool (set after registration)
    """
    name:         str
    description:  str
    input_schema: Dict[str, Any]
    categories:   List[str] = field(default_factory=list)
    requires_key: bool      = False
    enabled:      bool      = True
    handler:      Optional[Callable[[Dict[str, Any]], Any]] = field(default=None, repr=False)

    def to_schema(self) -> Dict[str, Any]:
        """Return an Anthropic-compatible tool schema dict."""
        return {
            "name":         self.name,
            "description":  self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolResult:
    """Normalized output from a tool call.

    Attributes
    ----------
    tool_name   : name of the tool that was called
    success     : whether the call succeeded
    content     : main output (string, dict, or list)
    error       : error message if not successful
    latency_ms  : execution time
    metadata    : additional provenance metadata
    """
    tool_name:   str
    success:     bool
    content:     Any  = None
    error:       str  = ""
    latency_ms:  float = 0.0
    metadata:    Dict[str, Any] = field(default_factory=dict)


# ── ToolRegistry ───────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry of available tools with dispatch and schema export."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.debug(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def all_enabled(self) -> List[ToolDefinition]:
        return [t for t in self._tools.values() if t.enabled]

    def for_category(self, category: str) -> List[ToolDefinition]:
        return [t for t in self.all_enabled() if category in t.categories]

    def to_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return Anthropic-compatible tool schema list for all enabled tools."""
        return [t.to_schema() for t in self.all_enabled()]

    def call(self, name: str, tool_input: Dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name.

        Parameters
        ----------
        name       : registered tool name
        tool_input : input parameters matching the tool's input_schema

        Returns
        -------
        ToolResult  (success=False on any error)
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool_name=name, success=False,
                              error=f"Tool '{name}' not registered")
        if not tool.enabled:
            return ToolResult(tool_name=name, success=False,
                              error=f"Tool '{name}' is disabled")
        if tool.handler is None:
            return ToolResult(tool_name=name, success=False,
                              error=f"Tool '{name}' has no handler")

        t_start = time.time()
        try:
            content = tool.handler(tool_input)
            latency = (time.time() - t_start) * 1000
            return ToolResult(
                tool_name  = name,
                success    = True,
                content    = content,
                latency_ms = latency,
            )
        except Exception as exc:
            latency = (time.time() - t_start) * 1000
            logger.warning(f"Tool '{name}' call failed: {exc}")
            return ToolResult(
                tool_name  = name,
                success    = False,
                error      = str(exc),
                latency_ms = latency,
            )

    def dispatch(self, name: str, tool_input: Dict[str, Any]) -> ToolResult:
        """Alias for call(), matches Responses API dispatch pattern."""
        return self.call(name, tool_input)


# ── Default registry + built-in tools ────────────────────────────────────

tool_registry = ToolRegistry()


def _handler_company_profile(inp: Dict[str, Any]) -> Any:
    try:
        from ..providers.fmp_client import get_company_profile
        from ..config import settings
        return get_company_profile(inp.get("ticker", ""), api_key=settings.fmp_api_key)
    except Exception as exc:
        raise RuntimeError(f"company_profile failed: {exc}") from exc


def _handler_recent_filings(inp: Dict[str, Any]) -> Any:
    try:
        from ..providers.sec_client import get_recent_filings
        return get_recent_filings(inp.get("ticker", ""))
    except Exception as exc:
        raise RuntimeError(f"recent_filings failed: {exc}") from exc


def _handler_market_snapshot(inp: Dict[str, Any]) -> Any:
    try:
        from ..providers.fmp_client import get_market_snapshot
        from ..config import settings
        return get_market_snapshot(inp.get("ticker", ""), api_key=settings.fmp_api_key)
    except Exception as exc:
        raise RuntimeError(f"market_snapshot failed: {exc}") from exc


def _handler_retrieve(inp: Dict[str, Any]) -> Any:
    try:
        from .retrieval import RetrievalQuery, retrieve
        query   = RetrievalQuery(
            text        = inp.get("query", ""),
            company     = inp.get("company", ""),
            ticker      = inp.get("ticker", ""),
            max_results = int(inp.get("max_results", 5)),
        )
        ctx     = retrieve(query)
        return [
            {"title": r.title, "snippet": r.snippet, "source": r.source, "url": r.url}
            for r in ctx.results
        ]
    except Exception as exc:
        raise RuntimeError(f"retrieve failed: {exc}") from exc


def _handler_price_history(inp: Dict[str, Any]) -> Any:
    try:
        from .history_ops import history_ops
        window = history_ops.price_window(
            ticker = inp.get("ticker", ""),
            days   = inp.get("days"),
        )
        return {
            "domain":       window.domain,
            "ticker":       window.ticker,
            "record_count": window.record_count,
            "prices":       window.values("price"),
        }
    except Exception as exc:
        raise RuntimeError(f"price_history failed: {exc}") from exc


def _handler_analyze_company(inp: Dict[str, Any]) -> Any:
    """Tool wrapper for the full analysis workflow."""
    try:
        from ..schemas import AnalysisRequest
        from ..services.analysis_service import analyze_company
        req    = AnalysisRequest(
            company_name  = inp.get("company", ""),
            user_question = inp.get("question", ""),
        )
        result = analyze_company(req)
        return {
            "request_id": result.request_id,
            "final_verdict": getattr(result.synthesis, "final_verdict", None),
            "key_risks": getattr(result.synthesis, "key_risks_ranked", []),
        }
    except Exception as exc:
        raise RuntimeError(f"analyze_company tool failed: {exc}") from exc


# Register built-in tools
tool_registry.register(ToolDefinition(
    name        = "company_profile",
    description = "Retrieve company profile including name, sector, description, and CEO.",
    input_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol"}
        },
        "required": ["ticker"],
    },
    categories  = ["financial", "company"],
    requires_key = True,
    handler     = _handler_company_profile,
))

tool_registry.register(ToolDefinition(
    name        = "market_snapshot",
    description = "Retrieve current market price, volume, and market cap for a company.",
    input_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol"}
        },
        "required": ["ticker"],
    },
    categories  = ["financial", "market"],
    requires_key = True,
    handler     = _handler_market_snapshot,
))

tool_registry.register(ToolDefinition(
    name        = "recent_filings",
    description = "Retrieve recent SEC regulatory filings for a company.",
    input_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol or company name"}
        },
        "required": ["ticker"],
    },
    categories  = ["filings", "regulatory"],
    requires_key = False,
    handler     = _handler_recent_filings,
))

tool_registry.register(ToolDefinition(
    name        = "retrieve",
    description = (
        "Search for relevant news, documents, and public information "
        "about a company or topic."
    ),
    input_schema = {
        "type": "object",
        "properties": {
            "query":       {"type": "string", "description": "Search query"},
            "company":     {"type": "string", "description": "Company name filter"},
            "ticker":      {"type": "string", "description": "Ticker filter"},
            "max_results": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": ["query"],
    },
    categories  = ["retrieval", "search"],
    requires_key = False,
    handler     = _handler_retrieve,
))

tool_registry.register(ToolDefinition(
    name        = "price_history",
    description = "Retrieve historical price data for a ticker over a time window.",
    input_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol"},
            "days":   {"type": "integer", "description": "Number of days of history (optional)"},
        },
        "required": ["ticker"],
    },
    categories  = ["financial", "history"],
    requires_key = False,
    handler     = _handler_price_history,
))

tool_registry.register(ToolDefinition(
    name        = "analyze_company",
    description = (
        "Run a full AI analyst workflow for a company and return key findings "
        "including final verdict, risks, and drivers."
    ),
    input_schema = {
        "type": "object",
        "properties": {
            "company":  {"type": "string", "description": "Company name"},
            "question": {"type": "string", "description": "Optional analytical question"},
        },
        "required": ["company"],
    },
    categories  = ["analysis", "reasoning"],
    requires_key = False,
    handler     = _handler_analyze_company,
))
