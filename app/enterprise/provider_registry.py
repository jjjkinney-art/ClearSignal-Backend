"""
Provider governance layer — entitlements, capability metadata, fallback chains.

Sits between routing/evidence-selection and actual provider execution.
Answers three questions before any provider call is made:

    1. Is this provider allowed for this request type?
    2. Can the response from this provider be cited/exposed?
    3. If this provider fails, what is the fallback order?

Key abstractions
----------------
ProviderMetadata    : static facts about a provider (license, capabilities)
ProviderPolicy      : request-scoped policy (allowed providers, priority)
SourceAccessDecision: result of an entitlement check

Usage::

    decision = check_source_access("fmp", scope=ScopeContext(...))
    if decision.allowed:
        data = call_fmp(...)
    chain = get_provider_chain("financial", scope=scope)
    # chain = ["fmp", "sec", "public"]  in priority order
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Provider license / source type taxonomy ───────────────────────────────

class SourceType:
    PUBLIC   = "public"     # freely available, can always be cited
    LICENSED = "licensed"   # requires valid API key / subscription
    INTERNAL = "internal"   # internal proprietary data, never expose raw
    CACHED   = "cached"     # served from cache, cite as underlying source


class CapabilityType:
    COMPANY_PROFILE   = "company_profile"
    MARKET_SNAPSHOT   = "market_snapshot"
    FINANCIAL_HISTORY = "financial_history"
    FILINGS           = "filings"
    NEWS              = "news"
    RETRIEVAL         = "retrieval"
    DOCUMENT_SEARCH   = "document_search"
    WEB_SEARCH        = "web_search"


# ── ProviderMetadata ─────────────────────────────────────────────────────

@dataclass
class ProviderMetadata:
    """Static description of a data provider.

    Attributes
    ----------
    name            : canonical provider identifier (e.g. "fmp", "sec")
    source_type     : SourceType constant
    capabilities    : list of CapabilityType constants this provider supports
    timeout_s       : default request timeout in seconds
    max_retries     : default retry count
    citeable        : whether outputs can be surfaced/cited to end users
    requires_key    : whether an API key is required
    description     : human-readable description
    priority        : lower = higher priority in fallback chains
    enabled         : whether this provider is active
    """
    name:         str
    source_type:  str
    capabilities: List[str]
    timeout_s:    float = 10.0
    max_retries:  int   = 2
    citeable:     bool  = True
    requires_key: bool  = False
    description:  str   = ""
    priority:     int   = 50
    enabled:      bool  = True
    extra:        Dict[str, Any] = field(default_factory=dict)


# ── ProviderPolicy ────────────────────────────────────────────────────────

@dataclass
class ProviderPolicy:
    """Request-scoped access policy for a set of providers.

    Attributes
    ----------
    allowed_providers   : explicit allowlist; empty = all enabled providers allowed
    denied_providers    : explicit denylist (takes precedence over allowlist)
    max_providers       : cap on how many providers may be called per request
    require_citeable    : if True, only citeable sources may be used
    allow_internal      : if True, internal sources are permitted
    preferred_capability: which capability type is primary for this request
    """
    allowed_providers:    List[str] = field(default_factory=list)
    denied_providers:     List[str] = field(default_factory=list)
    max_providers:        int       = 5
    require_citeable:     bool      = True
    allow_internal:       bool      = False
    preferred_capability: str       = ""


# ── SourceAccessDecision ──────────────────────────────────────────────────

@dataclass
class SourceAccessDecision:
    """Result of evaluating whether a provider may be used.

    Attributes
    ----------
    provider    : the provider name being evaluated
    allowed     : whether the provider is permitted
    citeable    : whether outputs may be cited/exposed
    reason      : human-readable explanation for the decision
    fallback_to : recommended fallback provider if not allowed
    """
    provider:    str
    allowed:     bool
    citeable:    bool
    reason:      str
    fallback_to: Optional[str] = None


# ── ProviderRegistry ──────────────────────────────────────────────────────

class ProviderRegistry:
    """Central registry of all data providers.

    Providers are registered at startup.  The registry enforces
    entitlement checks and builds fallback chains at query time.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, ProviderMetadata] = {}

    def register(self, meta: ProviderMetadata) -> None:
        self._providers[meta.name] = meta
        logger.debug(f"Provider registered: {meta.name} (type={meta.source_type})")

    def get(self, name: str) -> Optional[ProviderMetadata]:
        return self._providers.get(name)

    def all_enabled(self) -> List[ProviderMetadata]:
        return [p for p in self._providers.values() if p.enabled]

    def for_capability(self, capability: str) -> List[ProviderMetadata]:
        """Return enabled providers that support the given capability, sorted by priority."""
        return sorted(
            [p for p in self.all_enabled() if capability in p.capabilities],
            key=lambda p: p.priority,
        )

    def check_access(
        self,
        provider_name: str,
        policy: Optional[ProviderPolicy] = None,
        has_api_key: bool = False,
    ) -> SourceAccessDecision:
        """Check whether a provider is accessible under the given policy.

        Rules (in priority order):
            1. Provider must exist and be enabled
            2. Provider must not be in denied_providers
            3. If allowed_providers is non-empty, provider must be in it
            4. If requires_key is True, has_api_key must be True
            5. If policy.require_citeable and not citeable → deny
            6. If source_type == internal and not policy.allow_internal → deny
        """
        meta = self._providers.get(provider_name)
        if meta is None:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=False,
                reason=f"Provider '{provider_name}' not registered",
            )
        if not meta.enabled:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=False,
                reason=f"Provider '{provider_name}' is disabled",
            )

        pol = policy or ProviderPolicy()

        if provider_name in pol.denied_providers:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=meta.citeable,
                reason=f"Provider '{provider_name}' is in the deny list",
            )

        if pol.allowed_providers and provider_name not in pol.allowed_providers:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=meta.citeable,
                reason=f"Provider '{provider_name}' not in allowed list",
            )

        if meta.requires_key and not has_api_key:
            # Soft deny: not an error, but can't use without key
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=meta.citeable,
                reason=f"Provider '{provider_name}' requires an API key",
                fallback_to=self._find_fallback(provider_name, pol),
            )

        if pol.require_citeable and not meta.citeable:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=False,
                reason=f"Provider '{provider_name}' is not citeable (policy requires citeable)",
            )

        if meta.source_type == SourceType.INTERNAL and not pol.allow_internal:
            return SourceAccessDecision(
                provider=provider_name, allowed=False, citeable=False,
                reason=f"Provider '{provider_name}' is internal; policy does not allow internal sources",
            )

        return SourceAccessDecision(
            provider=provider_name, allowed=True, citeable=meta.citeable,
            reason="Access granted",
        )

    def _find_fallback(
        self, provider_name: str, policy: ProviderPolicy
    ) -> Optional[str]:
        """Find the next best provider that passes the policy."""
        meta = self._providers.get(provider_name)
        if meta is None:
            return None
        for candidate in self.for_capability(meta.capabilities[0] if meta.capabilities else ""):
            if candidate.name != provider_name:
                dec = self.check_access(candidate.name, policy, has_api_key=True)
                if dec.allowed:
                    return candidate.name
        return None

    def build_chain(
        self,
        capability: str,
        policy: Optional[ProviderPolicy] = None,
        has_api_key: bool = True,
    ) -> List[str]:
        """Build an ordered fallback chain for a capability.

        Returns a list of provider names in priority order, excluding
        denied or unavailable ones.
        """
        pol     = policy or ProviderPolicy()
        candidates = self.for_capability(capability)
        chain: List[str] = []
        for p in candidates:
            dec = self.check_access(p.name, pol, has_api_key=has_api_key)
            if dec.allowed:
                chain.append(p.name)
            if pol.max_providers and len(chain) >= pol.max_providers:
                break
        return chain


# ── Default registry instance ─────────────────────────────────────────────

provider_registry = ProviderRegistry()

# Register built-in providers
provider_registry.register(ProviderMetadata(
    name         = "fmp",
    source_type  = SourceType.LICENSED,
    capabilities = [
        CapabilityType.COMPANY_PROFILE,
        CapabilityType.MARKET_SNAPSHOT,
        CapabilityType.FINANCIAL_HISTORY,
        CapabilityType.NEWS,
    ],
    timeout_s    = 10.0,
    max_retries  = 2,
    citeable     = True,
    requires_key = True,
    description  = "Financial Modeling Prep — financial data",
    priority     = 10,
))

provider_registry.register(ProviderMetadata(
    name         = "sec",
    source_type  = SourceType.PUBLIC,
    capabilities = [CapabilityType.FILINGS],
    timeout_s    = 15.0,
    max_retries  = 2,
    citeable     = True,
    requires_key = False,
    description  = "SEC EDGAR — public regulatory filings",
    priority     = 20,
))

provider_registry.register(ProviderMetadata(
    name         = "retrieval",
    source_type  = SourceType.PUBLIC,
    capabilities = [
        CapabilityType.RETRIEVAL,
        CapabilityType.NEWS,
        CapabilityType.DOCUMENT_SEARCH,
    ],
    timeout_s    = 12.0,
    max_retries  = 1,
    citeable     = True,
    requires_key = False,
    description  = "Public retrieval / document search",
    priority     = 30,
))

provider_registry.register(ProviderMetadata(
    name         = "web_search",
    source_type  = SourceType.PUBLIC,
    capabilities = [CapabilityType.WEB_SEARCH, CapabilityType.NEWS],
    timeout_s    = 8.0,
    max_retries  = 1,
    citeable     = True,
    requires_key = False,
    description  = "Web search tool integration",
    priority     = 40,
    enabled      = False,   # enabled when tool integration is active
))


# ── Module-level convenience functions ───────────────────────────────────

def check_source_access(
    provider_name: str,
    policy: Optional[ProviderPolicy] = None,
    has_api_key: bool = False,
) -> SourceAccessDecision:
    """Check access for a provider against the default registry."""
    return provider_registry.check_access(provider_name, policy, has_api_key)


def get_provider_chain(
    capability: str,
    policy: Optional[ProviderPolicy] = None,
    has_api_key: bool = True,
) -> List[str]:
    """Build a fallback chain for a capability using the default registry."""
    return provider_registry.build_chain(capability, policy, has_api_key)
