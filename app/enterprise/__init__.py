"""
Enterprise hardening package for the AI analyst backend.

This package adds institutional-grade operational capabilities on top of
the existing meaning-first reasoning architecture without modifying it.

Modules
-------
observability   : request tracing, structured spans, latency metrics
provider_registry : provider governance, entitlements, fallback chains
audit           : reproducibility records for analysis, alerts, monitoring
retrieval       : centralized retrieval abstraction with ranking and freshness
history_ops     : typed history query layer with windowed access
reliability     : circuit breaker, retry policy, source health tracking
tenant          : user/tenant scope hooks for future multi-tenancy
cache           : lightweight in-process TTL cache with observability
tools           : tool-integration abstraction for modern agent stacks
"""

from .observability import (
    Span,
    RequestTrace,
    get_tracer,
    start_span,
)
from .provider_registry import (
    ProviderMetadata,
    ProviderPolicy,
    SourceAccessDecision,
    provider_registry,
    check_source_access,
    get_provider_chain,
)
from .audit import (
    AnalysisAuditRecord,
    AlertAuditRecord,
    MonitoringDecisionRecord,
    AuditStore,
    audit_store,
)
from .retrieval import (
    RetrievalQuery,
    RetrievalResult,
    RetrievalContext,
    retrieve,
)
from .history_ops import (
    HistoryWindow,
    HistoryOps,
    history_ops,
)
from .reliability import (
    ProviderHealth,
    RetryPolicy,
    CircuitBreaker,
    provider_health,
    call_with_reliability,
)
from .tenant import (
    TenantScope,
    UserScope,
    ScopeContext,
    get_scope,
)
from .cache import (
    CacheEntry,
    InProcessCache,
    response_cache,
    history_cache,
)
from .tools import (
    ToolDefinition,
    ToolResult,
    ToolRegistry,
    tool_registry,
)

__all__ = [
    # observability
    "Span", "RequestTrace", "get_tracer", "start_span",
    # provider governance
    "ProviderMetadata", "ProviderPolicy", "SourceAccessDecision",
    "provider_registry", "check_source_access", "get_provider_chain",
    # audit
    "AnalysisAuditRecord", "AlertAuditRecord", "MonitoringDecisionRecord",
    "AuditStore", "audit_store",
    # retrieval
    "RetrievalQuery", "RetrievalResult", "RetrievalContext", "retrieve",
    # history
    "HistoryWindow", "HistoryOps", "history_ops",
    # reliability
    "ProviderHealth", "RetryPolicy", "CircuitBreaker",
    "provider_health", "call_with_reliability",
    # tenant
    "TenantScope", "UserScope", "ScopeContext", "get_scope",
    # cache
    "CacheEntry", "InProcessCache", "response_cache", "history_cache",
    # tools
    "ToolDefinition", "ToolResult", "ToolRegistry", "tool_registry",
]
