"""
Evidence selection and building service.

This module contains simple heuristics for selecting which evidence
sources to query based on a user question and functions to fetch
and normalize evidence into the ``GroundingContext``.  The purpose
is to decouple external data retrieval from the business logic in
``analysis_service`` and to provide a centralized location for
extending evidence integrations.

The selection and builder functions return structured metadata so
that the caller can trace the decisions made during routing and
evidence gathering.  Graceful fallback behavior ensures that
failures in external services do not break the analysis workflow.
"""

from __future__ import annotations

import copy
import logging
from typing import Dict, List, Any, Optional

from ..schemas import GroundingContext, CompanyProfile, MarketSnapshot, FinancialContext, FilingContext
from ..providers import (
    get_recent_filings,
    get_company_facts,
    get_company_profile,
    get_market_snapshot,
    get_financial_context,
    get_recent_news,
    get_public_context,
    get_document_context,
)
from datetime import datetime, timezone

# Import data pipeline schemas and storage functions to persist evidence.
try:
    # Prefer relative import of the data pipeline to avoid cyclic dependencies.
    from ..data_pipeline.schemas import PriceRecord, FinancialRecord, EventRecord  # type: ignore
    from ..data_pipeline.storage import (
        insert_price_records,
        insert_financial_records,
        insert_event_records,
    )  # type: ignore
except Exception:
    # In case the data pipeline is unavailable, define no‑op placeholders.
    PriceRecord = None  # type: ignore
    FinancialRecord = None  # type: ignore
    EventRecord = None  # type: ignore
    def insert_price_records(*args, **kwargs):  # type: ignore
        return None
    def insert_financial_records(*args, **kwargs):  # type: ignore
        return None
    def insert_event_records(*args, **kwargs):  # type: ignore
        return None
from ..config import settings

logger = logging.getLogger(__name__)

# ── Null context manager (used when tracing is unavailable) ───────────────
from contextlib import contextmanager as _contextmanager

@_contextmanager
def _null_ctx():
    """No-op context manager used when a trace is not available."""
    class _Noop:
        def set_tag(self, *a, **kw): pass
    yield _Noop()

# ── Enterprise layer integration ──────────────────────────────────────────
# Import enterprise modules.  All imports are guarded so the service
# degrades gracefully when running in minimal/test environments.
try:
    from ..enterprise.cache import response_cache, provider_cache_key
    from ..enterprise.provider_registry import (
        provider_registry, check_source_access, ProviderPolicy,
        CapabilityType,
    )
    from ..enterprise.reliability import call_with_reliability, RetryPolicy
    from ..enterprise.history_ops import history_ops
    from ..enterprise.observability import get_existing_trace, start_span
    from ..enterprise.tenant import ScopeContext
    _ENTERPRISE = True
except Exception:
    _ENTERPRISE = False
    response_cache = None  # type: ignore
    provider_registry = None  # type: ignore
    history_ops = None  # type: ignore

# Retain the old local dict as a no-eviction fallback when the enterprise
# cache is unavailable (test/offline environments).
_EVIDENCE_CACHE_FALLBACK: Dict[Any, Any] = {}


def _cache_get(key: Any) -> Any:
    """Get from enterprise cache, fallback to local dict."""
    if _ENTERPRISE and response_cache is not None:
        k = str(key)
        return response_cache.get(k)
    return _EVIDENCE_CACHE_FALLBACK.get(key)


def _cache_set(key: Any, value: Any) -> None:
    """Set in enterprise cache and local dict."""
    if _ENTERPRISE and response_cache is not None:
        k = str(key)
        response_cache.set(k, value, ttl_s=getattr(settings, "provider_cache_ttl_s", 300.0),
                           source_tags=[str(key[0]) if isinstance(key, tuple) else "evidence"])
    _EVIDENCE_CACHE_FALLBACK[key] = value


def _check_provider_access(
    provider_name: str,
    has_key: bool = False,
    scope: "ScopeContext | None" = None,
) -> bool:
    """Check provider access through governance layer.

    Returns True when the provider is accessible given current policy.
    When enterprise is disabled, always returns True (open fallback).
    When scope restricts sources, also enforces that restriction.
    """
    if scope is not None and not scope.can_access_source(provider_name):
        logger.info(f"Source '{provider_name}' blocked by scope restrictions")
        return False
    if not _ENTERPRISE or provider_registry is None:
        return True
    try:
        policy = ProviderPolicy(require_citeable=True)
        decision = provider_registry.check_access(provider_name, policy=policy,
                                                   has_api_key=has_key)
        if not decision.allowed:
            logger.info(f"Provider '{provider_name}' denied by governance: {decision.reason}")
        return decision.allowed
    except Exception:
        return True   # fail-open on governance errors


def _governed_call(
    provider_name: str,
    fn: "Any",
    has_key: bool = False,
    scope: "ScopeContext | None" = None,
    fallback: "Any | None" = None,
) -> "Any":
    """Execute a provider call through governance + reliability wrappers."""
    if not _check_provider_access(provider_name, has_key=has_key, scope=scope):
        return fallback() if callable(fallback) else None
    if not _ENTERPRISE:
        try:
            return fn()
        except Exception:
            return fallback() if callable(fallback) else None
    try:
        meta = provider_registry.get(provider_name) if provider_registry else None
        policy = RetryPolicy(
            max_retries = getattr(meta, "max_retries", 2),
        )
        return call_with_reliability(
            provider_name = provider_name,
            fn            = fn,
            policy        = policy,
            fallback_fn   = fallback,
        )
    except Exception:
        return fallback() if callable(fallback) else None


# Keyword patterns for deciding which evidence sources to query.  Each
# key corresponds to an evidence source and maps to a list of
# case‑insensitive keywords.  When a keyword is found in the user
# question, the corresponding source becomes relevant.  If no keywords
# match, FMP and SEC are selected by default to provide a baseline of
# financial and filings information.
EVIDENCE_KEYWORDS: Dict[str, List[str]] = {
    "sec": ["sec", "filing", "10-k", "10‑k", "10-q", "annual report", "quarterly report", "form", "edgar"],
    "fmp": ["financial", "income", "earnings", "revenue", "profit", "market cap", "quote", "price", "valuation", "statement"],
    "retrieval": ["news", "press release", "recent", "latest", "update", "document", "transcript", "public"],
}


def select_evidence_sources(question: Optional[str]) -> Dict[str, Any]:
    """Select evidence sources based on the question.

    Parameters
    ----------
    question : Optional[str]
        The user's question.  If ``None`` or empty, default sources
        (FMP and SEC) are selected.

    Returns
    -------
    Dict[str, Any]
        Structured metadata including ``selected_sources``,
        ``skipped_sources``, ``reasons``, and ``confidence``.
    """
    text = question.lower() if question else ""
    matched: Dict[str, List[str]] = {}
    for source, keywords in EVIDENCE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.setdefault(source, []).append(kw)
    # Determine selection order by the order of keys in EVIDENCE_KEYWORDS
    ordered = [s for s in EVIDENCE_KEYWORDS.keys() if s in matched]
    if not ordered:
        # Default to baseline FMP and SEC if nothing matches
        ordered = ["fmp", "sec"]
    skipped = [s for s in EVIDENCE_KEYWORDS.keys() if s not in ordered]
    reasons: Dict[str, str] = {}
    for src in ordered:
        kws = matched.get(src)
        if kws:
            display = ", ".join(kws[:3])
            if len(kws) > 3:
                display += ", ..."
            reasons[src] = f"matched keywords: {display}"
        else:
            reasons[src] = "default source"
    for src in skipped:
        reasons[src] = "no relevant keywords"
    # Confidence: fraction of matched keyword occurrences to total word count
    total_matches = sum(len(v) for v in matched.values())
    import re
    words = re.findall(r"\b\w+\b", text)
    word_count = len(words) if words else 1
    confidence = min(1.0, total_matches / word_count) if total_matches else 0.0
    return {
        "selected_sources": ordered,
        "skipped_sources": skipped,
        "reasons": reasons,
        "confidence": confidence,
    }


def build_evidence(
    company: str,
    ticker: Optional[str],
    question: Optional[str],
    sources: List[str],
    context: GroundingContext,
) -> GroundingContext:
    """Fetch and normalize evidence from the selected sources.

    This function populates the ``GroundingContext`` with structured
    evidence.  For each selected source, the appropriate provider
    functions are called.  Failures are logged and skipped.  After
    gathering evidence, the function ensures that missing fields are
    filled with meaningful placeholders so that prompts receive
    operational context.

    Parameters
    ----------
    company : str
        Company name.
    ticker : Optional[str]
        Ticker symbol (may be None or empty).
    question : Optional[str]
        User question.
    sources : List[str]
        List of selected evidence source identifiers (e.g. ``"sec"``,
        ``"fmp"``, ``"retrieval"``).
    context : GroundingContext
        Existing grounding context to enrich.

    Returns
    -------
    GroundingContext
        The enriched context with placeholders filled.
    """
    # Deep-copy the caller's context so that the original is never mutated.
    # All callers capture the return value via ``ctx = build_evidence(...)``,
    # and the deep-copy contract ensures original contexts remain pristine.
    ctx = copy.deepcopy(context)

    # ── Observability: get trace for this request if one exists ──────────
    trace = None
    request_id = getattr(context, "request_id", None) or ""
    if _ENTERPRISE and request_id:
        try:
            from ..enterprise.observability import get_existing_trace
            trace = get_existing_trace(request_id)
        except Exception:
            pass

    # ── Historical storage enrichment via history_ops ─────────────────────
    # All history queries now go through history_ops.  This enforces
    # centralized, governance-ready history access with windowed queries
    # and consistent interfaces.
    try:
        _hops = history_ops  # always the enterprise HistoryOps singleton
        if _hops is None:
            # Enterprise disabled: use empty windows (no storage access)
            class _EmptyOps:
                def price_window(self, **kw):
                    class _W:
                        records = []
                    return _W()
                financial_window = signal_window = event_window = price_window
            _hops = _EmptyOps()

        # ── Span: historical data access ──────────────────────────────────
        _span_ctx = start_span(trace, "history_access") if (trace and _ENTERPRISE) else None

        # Price history via history_ops
        try:
            price_window = _hops.price_window(ticker=ticker or company, days=180, limit=100)
            price_rows   = price_window.records
        except Exception:
            price_rows = []

        prices: List[float] = []
        for row in price_rows:
            try:
                val = row.get("price")
                if val is not None:
                    prices.append(float(val))
            except Exception:
                continue
        if prices:
            n = len(prices)
            avg_price = sum(prices) / n
            sorted_prices = sorted(prices)
            mid = n // 2
            if n % 2 == 0:
                median_price = (sorted_prices[mid - 1] + sorted_prices[mid]) / 2.0
            else:
                median_price = sorted_prices[mid]
            mean_price = avg_price
            variance = sum((p - mean_price) ** 2 for p in prices) / n if n > 0 else 0.0
            from math import sqrt
            volatility = sqrt(variance) if variance >= 0 else 0.0
            min_price = min(prices)
            max_price = max(prices)
            ctx.financials.setdefault("avg_price", avg_price)
            ctx.financials.setdefault("median_price", median_price)
            ctx.financials.setdefault("price_volatility", volatility)
            ctx.financials.setdefault("min_price", min_price)
            ctx.financials.setdefault("max_price", max_price)
            # NOTE: raw statistical summary is NOT appended to known_facts.
            # Raw numbers live in ctx.financials and later in
            # HistoricalMeaning.supporting_metrics.  known_facts will receive
            # the MEANING summary built below.
            ctx.source_notes.append("Historical price statistics (raw in supporting_metrics)")

        # Financial history via history_ops
        try:
            fin_window = _hops.financial_window(ticker=ticker or company, days=365, limit=100)
            fin_rows   = fin_window.records
        except Exception:
            fin_rows = []

        metrics: Dict[str, List[tuple]] = {}
        for row in fin_rows:
            name  = row.get("metric_name")
            value = row.get("value")
            ts    = row.get("timestamp")
            if name and value is not None:
                try:
                    metrics.setdefault(name, []).append((ts, float(value)))
                except Exception:
                    continue
        for mname in ("revenue", "net_income", "ebitda", "eps"):
            rows = metrics.get(mname, [])
            if rows:
                values = [v for _, v in rows]
                count  = len(values)
                avg_val    = sum(values) / count
                sorted_vals = sorted(values)
                mid_i = count // 2
                median_val = (
                    (sorted_vals[mid_i - 1] + sorted_vals[mid_i]) / 2.0
                    if count % 2 == 0 else sorted_vals[mid_i]
                )
                ctx.financials.setdefault(f"avg_{mname}", avg_val)
                ctx.financials.setdefault(f"median_{mname}", median_val)
                # NOTE: raw financial-stat summary no longer appended to known_facts.
                # Numbers remain in ctx.financials and flow into HistoricalMeaning.supporting_metrics.
                ctx.source_notes.append(f"Historical {mname} statistics (raw in supporting_metrics)")
                valid_rows: List[tuple] = []
                from datetime import datetime as _dt
                for ts, val in rows:
                    if ts:
                        try:
                            valid_rows.append((_dt.fromisoformat(str(ts)), val))
                        except Exception:
                            pass
                if len(valid_rows) >= 2:
                    valid_rows.sort(key=lambda x: x[0])
                    first_val = valid_rows[0][1]
                    last_val  = valid_rows[-1][1]
                    if first_val != 0:
                        change = (last_val - first_val) / first_val
                        if change > 0.05:
                            trend = "upward"
                        elif change < -0.05:
                            trend = "downward"
                        else:
                            trend = "stable"
                        ctx.financials.setdefault(f"{mname}_trend", trend)
                        # MEANING-FIRST: do NOT append raw trend label to known_facts.
                        # The trend label survives in ctx.financials for downstream
                        # meaning construction and ends up under supporting_metrics
                        # on the resulting HistoricalMeaning.
                        ctx.source_notes.append("Historical trend analysis (supporting_metrics only)")

        # Event history via history_ops
        try:
            event_window = _hops.event_window(ticker=ticker or company, days=180, limit=100)
            event_rows   = event_window.records
        except Exception:
            event_rows = []

        # Signal history via history_ops
        try:
            sig_window = _hops.signal_window(days=90, limit=100)
            sig_rows   = sig_window.records
        except Exception:
            sig_rows = []

        if _span_ctx is not None:
            try:
                _span_ctx.__exit__(None, None, None)
                _span = None
            except Exception:
                pass
        if event_rows:
            from collections import Counter
            counts: Counter[str] = Counter()
            for row in event_rows:
                etype = row.get("event_type")
                if etype:
                    counts[str(etype)] += 1
            if counts:
                summary_parts: List[str] = []
                for etype, count in counts.items():
                    # Pluralize event type when count >1 by adding 's' if not already plural
                    plural = etype if etype.endswith("s") else f"{etype}s"
                    summary_parts.append(f"{count} {plural}")
                summary_str = ", ".join(summary_parts)
                # MEANING-FIRST: do NOT append raw event-count summary to known_facts.
                # The counts feed into HistoricalMeaning.supporting_metrics below.
                # Save the summary string on context for the meaning builder to consume.
                try:
                    ctx.financials.setdefault("_event_count_summary", summary_str)
                except Exception:
                    pass
                ctx.source_notes.append("Historical event summary (supporting_metrics only)")

                # Interpretive historical metrics: compute trend direction, strength, volatility regime,
                # pattern behaviour, signal and alert frequency changes, repeated event patterns and event
                # frequency trends. Store these in the financials dict and append a combined interpretive
                # summary to known_facts for reasoning-ready context.
                try:
                    trend_direction = "stable"
                    trend_strength = "weak"
                    volatility_regime = "stable"
                    pattern_behavior = "isolated"
                    # Price-based interpretive metrics
                    if prices:
                        first_val = prices[0]
                        last_val = prices[-1]
                        pct_change = 0.0
                        if first_val:
                            pct_change = (last_val - first_val) / abs(first_val)
                        if pct_change > 0.05:
                            trend_direction = "rising"
                        elif pct_change < -0.05:
                            trend_direction = "falling"
                        else:
                            trend_direction = "stable"
                        abs_change = abs(pct_change)
                        if abs_change > 0.2:
                            trend_strength = "strong"
                        elif abs_change > 0.1:
                            trend_strength = "moderate"
                        else:
                            trend_strength = "weak"
                        import math as _math
                        mean_price = sum(prices) / len(prices)
                        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
                        vol = _math.sqrt(variance) if variance >= 0 else 0.0
                        vol_ratio = (vol / mean_price) if mean_price else 0.0
                        if vol_ratio > 0.1:
                            volatility_regime = "volatile"
                        elif vol_ratio < 0.05:
                            volatility_regime = "stable"
                        else:
                            volatility_regime = "shifting"
                        diffs = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
                        sign_changes = 0
                        for i in range(len(diffs)-1):
                            if (diffs[i] >= 0) != (diffs[i+1] >= 0):
                                sign_changes += 1
                        if diffs:
                            if sign_changes > len(diffs) * 0.5:
                                pattern_behavior = "cyclical"
                            else:
                                max_move = max(abs(d) for d in diffs)
                                if vol > 0 and max_move > 2 * vol:
                                    pattern_behavior = "isolated"
                                else:
                                    pattern_behavior = "clustering"
                    # Signal frequency change using signal_history (from history_ops above)
                    signal_freq_change = "stable"
                    alert_freq_trend = "stable"
                    event_freq_trend = "stable"
                    repeated_event_patterns = "rare"
                    # sig_rows already fetched via history_ops above
                    if sig_rows:
                        half = len(sig_rows) // 2
                        first_part = sig_rows[:half] or []
                        second_part = sig_rows[half:] or []
                        if len(first_part) > 0:
                            change = (len(second_part) - len(first_part)) / float(len(first_part))
                            if change > 0.1:
                                signal_freq_change = "increasing"
                            elif change < -0.1:
                                signal_freq_change = "decreasing"
                            else:
                                signal_freq_change = "stable"
                    # Event frequency and patterns
                    if event_rows:
                        ts_values = []
                        for row in event_rows:
                            ts = row.get("timestamp") or row.get("ts") or row.get("time")
                            if ts:
                                try:
                                    from datetime import datetime as _dt
                                    ts_values.append(_dt.fromisoformat(str(ts)))
                                except Exception:
                                    pass
                        if len(ts_values) >= 4:
                            ts_values.sort()
                            halfn = len(ts_values) // 2
                            first_half = ts_values[:halfn]
                            second_half = ts_values[halfn:]
                            if first_half:
                                change = (len(second_half) - len(first_half)) / float(len(first_half))
                                if change > 0.1:
                                    event_freq_trend = "increasing"
                                elif change < -0.1:
                                    event_freq_trend = "decreasing"
                                else:
                                    event_freq_trend = "stable"
                        from collections import Counter as _Counter
                        etypes = [row.get("event_type") for row in event_rows if row.get("event_type")]
                        cts = _Counter(etypes)
                        repeats = [c for c in cts.values() if c > 1]
                        if repeats:
                            if len(repeats) > len(cts) / 2:
                                repeated_event_patterns = "common"
                            else:
                                repeated_event_patterns = "uncommon"
                        else:
                            repeated_event_patterns = "rare"
                    # Determine additional interpretive metrics by examining event types and
                    # relationships between price behaviour and event frequencies.  The goal is
                    # to surface deeper patterns for reasoning, such as whether a single
                    # event type dominates the history, how diverse the event mix is, how
                    # price trends correlate with event frequency trends, and what the
                    # overall risk profile looks like when combining volatility and trend
                    # direction.  These heuristics are deliberately simple but informative.
                    dominant_event_type: str | None = None
                    event_diversity: str | None = None
                    price_event_correlation: str | None = None
                    risk_profile: str | None = None
                    try:
                        # Compute dominant event type and diversity
                        if counts:
                            total_events = sum(counts.values())
                            # Identify the event type with the highest count
                            dominant_event_type = max(counts.items(), key=lambda x: x[1])[0]
                            # Determine diversity based on the share of the dominant type
                            dom_ratio = counts[dominant_event_type] / float(total_events) if total_events > 0 else 0.0
                            if dom_ratio > 0.7:
                                event_diversity = "concentrated"
                            elif dom_ratio < 0.4:
                                event_diversity = "diverse"
                            else:
                                event_diversity = "mixed"
                        # Derive price‑event correlation from trend and event frequency trend
                        if trend_direction and event_freq_trend:
                            if trend_direction == "rising" and event_freq_trend == "increasing":
                                price_event_correlation = "positive"
                            elif trend_direction == "falling" and event_freq_trend == "increasing":
                                price_event_correlation = "negative"
                            elif trend_direction == "rising" and event_freq_trend == "decreasing":
                                price_event_correlation = "inverse"
                            elif trend_direction == "falling" and event_freq_trend == "decreasing":
                                price_event_correlation = "inverse"
                            else:
                                price_event_correlation = "neutral"
                        # Risk profile combines volatility and trend to indicate the
                        # qualitative nature of recent price action.
                        if volatility_regime and trend_direction:
                            if volatility_regime == "volatile" and trend_direction == "rising":
                                risk_profile = "momentum_high_risk"
                            elif volatility_regime == "volatile" and trend_direction == "falling":
                                risk_profile = "decline_high_risk"
                            elif volatility_regime in ("stable", "shifting") and trend_direction == "rising":
                                risk_profile = "steady_growth"
                            elif volatility_regime in ("stable", "shifting") and trend_direction == "falling":
                                risk_profile = "steady_decline"
                            else:
                                risk_profile = "stagnant"
                    except Exception:
                        # Suppress any errors in the interpretive heuristics
                        pass
                    # Update financials dictionary with interpretive metrics
                    ctx.financials.setdefault("trend_direction", trend_direction)
                    ctx.financials.setdefault("trend_strength", trend_strength)
                    ctx.financials.setdefault("volatility_regime", volatility_regime)
                    ctx.financials.setdefault("pattern_behavior", pattern_behavior)
                    ctx.financials.setdefault("signal_frequency_change", signal_freq_change)
                    ctx.financials.setdefault("alert_frequency_trend", alert_freq_trend)
                    ctx.financials.setdefault("repeated_event_patterns", repeated_event_patterns)
                    ctx.financials.setdefault("event_frequency_trend", event_freq_trend)
                    if dominant_event_type:
                        ctx.financials.setdefault("dominant_event_type", dominant_event_type)
                    if event_diversity:
                        ctx.financials.setdefault("event_diversity", event_diversity)
                    if price_event_correlation:
                        ctx.financials.setdefault("price_event_correlation", price_event_correlation)
                    if risk_profile:
                        ctx.financials.setdefault("risk_profile", risk_profile)
                    # ------------------------------------------------------------------
                    # MEANING-FIRST INTERPRETATIONS
                    #
                    # Build per-domain interpretation strings and historical
                    # implications.  These are STRUCTURED key/value entries that
                    # feed ctx.financials for backward compatibility — they are
                    # NEVER appended to known_facts as human-readable strings.
                    # The interpretive narrative is fully owned by HistoricalMeaning
                    # objects constructed below.
                    # ------------------------------------------------------------------
                    interpretations: dict[str, str] = {}
                    # Price behavior interpretation
                    try:
                        price_clause = f"{trend_strength} {trend_direction} trend with {volatility_regime} volatility"
                        if price_event_correlation and price_event_correlation != "neutral":
                            price_clause += f" and {price_event_correlation} price-event correlation"
                        interpretations["price_pattern_interpretation"] = price_clause
                        interpretations["price_historical_implication"] = ""
                    except Exception:
                        pass
                    # Financial behavior interpretation
                    try:
                        fin_parts: list[str] = []
                        for m in ("revenue", "net_income", "ebitda", "eps"):
                            tr = ctx.financials.get(f"{m}_trend")
                            if tr:
                                fin_parts.append(f"{m.replace('_', ' ')} is {tr}")
                        if fin_parts:
                            interpretations["financial_pattern_interpretation"] = "; ".join(fin_parts)
                            interpretations["financial_historical_implication"] = ""
                        else:
                            interpretations["financial_pattern_interpretation"] = "no significant pattern"
                            interpretations["financial_historical_implication"] = ""
                    except Exception:
                        interpretations.setdefault("financial_pattern_interpretation", "no significant pattern")
                        interpretations.setdefault("financial_historical_implication", "")
                    # Event behavior interpretation
                    try:
                        event_parts: list[str] = []
                        if repeated_event_patterns:
                            event_parts.append(f"event patterns are {repeated_event_patterns}")
                        if event_diversity:
                            event_parts.append(f"event landscape is {event_diversity}")
                        if event_freq_trend:
                            event_parts.append(f"frequency is {event_freq_trend}")
                        if event_parts:
                            interpretations["event_pattern_interpretation"] = ", ".join(event_parts)
                            interpretations["event_historical_implication"] = ""
                    except Exception:
                        pass
                    # Signal behavior interpretation
                    try:
                        sig_parts: list[str] = []
                        if signal_freq_change:
                            sig_parts.append(f"signal frequency is {signal_freq_change}")
                        if alert_freq_trend:
                            sig_parts.append(f"alert frequency is {alert_freq_trend}")
                        if sig_parts:
                            interpretations["signal_pattern_interpretation"] = " and ".join(sig_parts)
                            interpretations["signal_historical_implication"] = ""
                    except Exception:
                        pass
                    # Alert behavior interpretation
                    try:
                        if alert_freq_trend:
                            interpretations["alert_pattern_interpretation"] = alert_freq_trend
                            interpretations["alert_historical_implication"] = ""
                    except Exception:
                        pass
                    # MEANING-FIRST: no interpretive summary strings are produced
                    # before HistoricalMeaning objects.  Raw stat labels live in
                    # the structured `interpretations` dict (which feeds
                    # ctx.financials for backward compat) and HistoricalMeaning
                    # owns the human-readable meaning narrative.
                    # Merge interpretations into the financials dict.  These keys
                    # represent the primary interpretive abstractions for each domain.
                    try:
                        for k, v in interpretations.items():
                            # Only set interpretation if not already present to avoid
                            # overriding existing data.  Interpretations are strings.
                            if k not in ctx.financials:
                                ctx.financials[k] = v
                    except Exception:
                        pass
                    # ------------------------------------------------------------------
                    # MEANING-NATIVE HISTORY OBJECTS
                    #
                    # Raw stats computed above are internal only.  This block derives
                    # HistoricalMeaning objects from the COMBINATION of stats — asking
                    # what the pattern means, not just labelling each stat.
                    #
                    # Archetype classification rules (applied to stat combinations):
                    #   "persistent-growth"   : rising trend + stable volatility
                    #   "stress-cluster"      : rising event freq + volatile/falling price
                    #   "structural-shift"    : strong trend change (>20%) in either direction
                    #   "fading-pattern"      : decreasing signal/event frequency + stable price
                    #   "noise-regime"        : stable trend + stable/low signal activity
                    #   "isolated-anomaly"    : any strong isolated movement without cluster
                    #   "deterioration"       : falling trend + volatile or increasing events
                    #   "recovery"            : rising price after prior falling + decreasing events
                    #
                    # usual_consequence is NOT derived from dominant outcome counts (that is
                    # the old metric-first shortcut).  It is derived from the archetype's
                    # canonical consequence, informed by signal profile when available.
                    try:
                        from ..schemas import HistoricalMeaning, HistoricalInterpretation  # type: ignore

                        # ---- Helper: infer situation archetype from stat combination ----
                        def _infer_price_archetype(
                            t_dir: str, t_str: str, vol: str, p_corr: str | None
                        ) -> str:
                            if t_str == "strong" and t_dir == "rising" and vol in ("stable", "shifting"):
                                return "persistent-growth"
                            if t_dir == "falling" and vol == "volatile":
                                return "deterioration"
                            if t_str == "strong" and t_dir == "falling":
                                return "structural-shift"
                            if t_str == "strong" and t_dir == "rising":
                                return "structural-shift"
                            if t_dir == "rising" and vol == "volatile" and p_corr == "positive":
                                return "stress-cluster"
                            if t_dir == "rising":
                                return "recovery"
                            if t_dir == "stable" and vol == "stable":
                                return "noise-regime"
                            return "isolated-anomaly"

                        def _infer_event_archetype(
                            e_freq: str, e_div: str | None, rep: str
                        ) -> str:
                            if e_freq == "increasing" and rep == "common":
                                return "stress-cluster"
                            if e_freq == "decreasing":
                                return "fading-pattern"
                            if rep == "common" and e_div in ("concentrated",):
                                return "structural-shift"
                            if e_freq == "stable" and rep == "rare":
                                return "noise-regime"
                            return "isolated-anomaly"

                        def _infer_signal_archetype(
                            s_freq: str, a_freq: str
                        ) -> str:
                            if s_freq == "increasing" and a_freq in ("increasing", "stable"):
                                return "stress-cluster"
                            if s_freq == "decreasing" and a_freq == "decreasing":
                                return "fading-pattern"
                            if s_freq == "stable" and a_freq == "stable":
                                return "noise-regime"
                            return "isolated-anomaly"

                        # ---- Canonical archetype → consequence (NOT from count dominance) ----
                        _ARCHETYPE_CONSEQUENCE: dict[str, str] = {
                            "persistent-growth":  "alert",
                            "stress-cluster":     "reanalysis",
                            "structural-shift":   "thesis_change",
                            "fading-pattern":     "alert",
                            "noise-regime":       "noise",
                            "isolated-anomaly":   "alert",
                            "deterioration":      "reanalysis",
                            "recovery":           "alert",
                        }

                        # ---- Canonical archetype → escalation likelihood ----
                        _ARCHETYPE_ESCALATION: dict[str, str] = {
                            "persistent-growth":  "low",
                            "stress-cluster":     "high",
                            "structural-shift":   "high",
                            "fading-pattern":     "low",
                            "noise-regime":       "low",
                            "isolated-anomaly":   "medium",
                            "deterioration":      "high",
                            "recovery":           "medium",
                        }

                        # ---- Pattern stability from volatility ----
                        def _stability(vol: str) -> str:
                            return {"volatile": "unstable", "stable": "stable", "shifting": "shifting"}.get(vol, "stable")

                        # ---- Pattern direction (meaning, not raw label) ----
                        def _meaning_direction(t_dir: str) -> str:
                            return {"rising": "improving", "falling": "deteriorating", "stable": "stable"}.get(t_dir, "stable")

                        # ---- Build price HistoricalMeaning ----
                        price_archetype = _infer_price_archetype(
                            trend_direction, trend_strength, volatility_regime, price_event_correlation
                        )
                        price_consequence = _ARCHETYPE_CONSEQUENCE.get(price_archetype, "alert")
                        price_meaning = HistoricalMeaning(
                            domain               = "price",
                            situation_archetype  = price_archetype,
                            historical_pattern   = (
                                f"Price has shown a {trend_strength} {trend_direction} trend "
                                f"with {volatility_regime} volatility"
                                + (f" and {price_event_correlation} price-event correlation" if price_event_correlation and price_event_correlation != "neutral" else "")
                                + "."
                            ),
                            pattern_stability    = _stability(volatility_regime),
                            pattern_direction    = _meaning_direction(trend_direction),
                            escalation_likelihood = _ARCHETYPE_ESCALATION.get(price_archetype, "medium"),
                            usual_consequence    = price_consequence,
                            meaning_summary      = (
                                f"Interpretive summary: Price pattern archetype: '{price_archetype}'. "
                                f"This regime historically tends toward {price_consequence} outcomes."
                            ),
                            supporting_metrics   = {
                                "trend_direction": trend_direction,
                                "trend_strength":  trend_strength,
                                "volatility_regime": volatility_regime,
                                "price_event_correlation": price_event_correlation,
                                "risk_profile": risk_profile,
                            },
                        )

                        # ---- Build event HistoricalMeaning ----
                        event_archetype = _infer_event_archetype(
                            event_freq_trend, event_diversity, repeated_event_patterns
                        )
                        event_consequence = _ARCHETYPE_CONSEQUENCE.get(event_archetype, "alert")
                        event_meaning = HistoricalMeaning(
                            domain               = "event",
                            situation_archetype  = event_archetype,
                            historical_pattern   = (
                                f"Event activity shows {event_freq_trend} frequency, "
                                f"{event_diversity or 'unknown'} diversity, "
                                f"with {repeated_event_patterns} repeated patterns."
                            ),
                            pattern_stability    = "stable" if event_freq_trend == "stable" else "shifting",
                            pattern_direction    = "deteriorating" if event_freq_trend == "increasing" and event_archetype in ("stress-cluster",) else "stable",
                            escalation_likelihood = _ARCHETYPE_ESCALATION.get(event_archetype, "medium"),
                            usual_consequence    = event_consequence,
                            meaning_summary      = (
                                f"Interpretive summary: Event pattern archetype: '{event_archetype}'. "
                                f"This event regime historically tends toward {event_consequence} outcomes."
                            ),
                            supporting_metrics   = {
                                "event_freq_trend":        event_freq_trend,
                                "event_diversity":         event_diversity,
                                "repeated_event_patterns": repeated_event_patterns,
                                "dominant_event_type":     dominant_event_type,
                            },
                        )

                        # ---- Build signal HistoricalMeaning ----
                        sig_archetype = _infer_signal_archetype(signal_freq_change, alert_freq_trend)
                        sig_consequence = _ARCHETYPE_CONSEQUENCE.get(sig_archetype, "alert")
                        signal_meaning = HistoricalMeaning(
                            domain               = "signal",
                            situation_archetype  = sig_archetype,
                            historical_pattern   = (
                                f"Signal frequency is {signal_freq_change}; "
                                f"alert frequency is {alert_freq_trend}."
                            ),
                            pattern_stability    = "stable" if signal_freq_change == "stable" else "shifting",
                            pattern_direction    = "deteriorating" if signal_freq_change == "increasing" else (
                                "improving" if signal_freq_change == "decreasing" else "stable"
                            ),
                            escalation_likelihood = _ARCHETYPE_ESCALATION.get(sig_archetype, "medium"),
                            usual_consequence    = sig_consequence,
                            meaning_summary      = (
                                f"Interpretive summary: Signal pattern archetype: '{sig_archetype}'. "
                                f"This signal regime historically tends toward {sig_consequence} outcomes."
                            ),
                            supporting_metrics   = {
                                "signal_freq_change": signal_freq_change,
                                "alert_freq_trend":   alert_freq_trend,
                            },
                        )

                        # ---- Build financial HistoricalMeaning ----
                        # Meaning-first: convert raw trends into semantic labels, then
                        # derive archetype from labels only (not from raw count dominance).
                        fin_trends = {m: ctx.financials.get(f"{m}_trend")
                                      for m in ("revenue", "net_income", "ebitda", "eps")
                                      if ctx.financials.get(f"{m}_trend")}
                        # Semantic labels derived from trend direction
                        fin_deteriorating = any(v == "downward" for v in fin_trends.values())
                        fin_improving     = any(v == "upward" for v in fin_trends.values())

                        # Semantic direction label (meaning-first)
                        if fin_deteriorating and fin_improving:
                            fin_direction_label = "divergent"
                        elif fin_deteriorating:
                            fin_direction_label = "falling"
                        elif fin_improving:
                            fin_direction_label = "rising"
                        else:
                            fin_direction_label = "stable"

                        # Meaning-first archetype inference from semantic label
                        def _infer_financial_archetype(direction: str) -> str:
                            if direction == "divergent":
                                return "isolated-anomaly"
                            if direction == "falling":
                                return "deterioration"
                            if direction == "rising":
                                return "persistent-growth"
                            return "noise-regime"

                        fin_arch         = _infer_financial_archetype(fin_direction_label)
                        fin_consequence  = _ARCHETYPE_CONSEQUENCE.get(fin_arch, "alert")
                        fin_pattern_desc = (
                            "; ".join(f"{m.replace('_', ' ')} trend: {v}"
                                      for m, v in fin_trends.items())
                            if fin_trends else "no directional trend available"
                        )
                        financial_meaning = HistoricalMeaning(
                            domain               = "financial",
                            situation_archetype  = fin_arch,
                            historical_pattern   = f"Financial metrics show: {fin_pattern_desc}.",
                            pattern_stability    = "unstable" if fin_direction_label == "divergent" else "stable",
                            pattern_direction    = _meaning_direction(fin_direction_label),
                            escalation_likelihood = _ARCHETYPE_ESCALATION.get(fin_arch, "medium"),
                            usual_consequence    = fin_consequence,
                            meaning_summary      = (
                                f"Interpretive summary: Financial pattern archetype: '{fin_arch}'. "
                                f"This financial regime historically tends toward {fin_consequence} outcomes."
                            ),
                            supporting_metrics   = {
                                "financial_trends":       fin_trends,
                                "financial_direction":    fin_direction_label,
                            },
                        )

                        # ---- Attach HistoricalMeaning objects as PRIMARY output ----
                        meaning_map: dict[str, HistoricalMeaning] = {
                            "price":     price_meaning,
                            "event":     event_meaning,
                            "signal":    signal_meaning,
                            "financial": financial_meaning,
                        }
                        try:
                            ctx.historical_meanings = meaning_map
                        except Exception:
                            try:
                                object.__setattr__(ctx, "historical_meanings", meaning_map)
                            except Exception:
                                pass

                        # ══════════════════════════════════════════════════════════
                        # MEANING-FIRST INVERSION
                        # ══════════════════════════════════════════════════════════
                        # known_facts now carries the MEANING summary of each domain's
                        # HistoricalMeaning object — not raw statistical bundles.
                        #
                        # Raw stats remain in supporting_metrics on each meaning object
                        # (accessible to downstream code that genuinely needs the number)
                        # but they no longer drive the primary evidence context.
                        try:
                            # Filter out any raw-stat facts previously appended by the
                            # statistical enrichment blocks.  These all start with known
                            # "Historical <domain> summary:" or "<metric> trend" prefixes.
                            _STAT_PREFIXES = (
                                "Historical price summary:",
                                "Historical revenue summary:",
                                "Historical net income summary:",
                                "Historical ebitda summary:",
                                "Historical eps summary:",
                                "Historical net_income summary:",
                                "Recent event history includes",
                            )
                            _STAT_TRAILS = (
                                " trend over the last ",  # "Revenue trend over the last N records is X."
                            )
                            def _is_raw_stat_fact(fact: str) -> bool:
                                if any(fact.startswith(p) for p in _STAT_PREFIXES):
                                    return True
                                if any(t in fact for t in _STAT_TRAILS):
                                    return True
                                return False

                            ctx.known_facts[:] = [
                                f for f in ctx.known_facts
                                if not _is_raw_stat_fact(f)
                            ]

                            # Append meaning summaries as the primary historical context.
                            for domain_name, m in meaning_map.items():
                                if m and m.meaning_summary:
                                    ctx.known_facts.append(m.meaning_summary)
                                    ctx.source_notes.append(
                                        f"HistoricalMeaning[{domain_name}]"
                                    )
                        except Exception:
                            pass

                        # ---- Backward-compat: also attach HistoricalInterpretation objects ----
                        # These are now derived FROM HistoricalMeaning, not from raw stats.
                        hist_objs: dict[str, HistoricalInterpretation] = {
                            "price": HistoricalInterpretation(
                                situation_type      = price_meaning.situation_archetype,
                                pattern_direction   = price_meaning.pattern_direction,
                                pattern_strength    = trend_strength,
                                historical_behavior = price_meaning.historical_pattern,
                                typical_outcome     = price_meaning.usual_consequence,
                                interpretation_summary = price_meaning.meaning_summary,
                            ),
                            "financial": HistoricalInterpretation(
                                situation_type      = financial_meaning.situation_archetype,
                                pattern_direction   = financial_meaning.pattern_direction,
                                pattern_strength    = None,
                                historical_behavior = financial_meaning.historical_pattern,
                                typical_outcome     = financial_meaning.usual_consequence,
                                interpretation_summary = financial_meaning.meaning_summary,
                            ),
                            "event": HistoricalInterpretation(
                                situation_type      = event_meaning.situation_archetype,
                                pattern_direction   = event_meaning.pattern_direction,
                                pattern_strength    = event_diversity,
                                historical_behavior = event_meaning.historical_pattern,
                                typical_outcome     = event_meaning.usual_consequence,
                                interpretation_summary = event_meaning.meaning_summary,
                            ),
                            "signal": HistoricalInterpretation(
                                situation_type      = signal_meaning.situation_archetype,
                                pattern_direction   = signal_meaning.pattern_direction,
                                pattern_strength    = None,
                                historical_behavior = signal_meaning.historical_pattern,
                                typical_outcome     = signal_meaning.usual_consequence,
                                interpretation_summary = signal_meaning.meaning_summary,
                            ),
                            "alert": HistoricalInterpretation(
                                situation_type      = signal_meaning.situation_archetype,
                                pattern_direction   = signal_meaning.pattern_direction,
                                pattern_strength    = None,
                                historical_behavior = None,
                                typical_outcome     = signal_meaning.usual_consequence,
                                interpretation_summary = signal_meaning.meaning_summary,
                            ),
                        }
                        try:
                            object.__setattr__(ctx, "historical_interpretations", hist_objs)
                        except Exception:
                            ctx.historical_interpretations = hist_objs  # type: ignore[attr-defined]
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        # Ignore any errors due to missing storage or query failures
        pass

    # ── Scope context extraction ──────────────────────────────────────────
    # The grounding context may carry a scope (set by the caller or API layer).
    scope: "ScopeContext | None" = getattr(context, "scope", None)

    # Determine symbol for FMP/SEC calls
    symbol = ticker or company
    # Track which structured fields were filled to aid placeholder logic
    filled_profile   = False
    filled_snapshot  = False
    filled_financial = False
    filled_filings   = False

    has_fmp_key = bool(getattr(settings, "fmp_api_key", ""))

    for src in sources:
        if src == "fmp":
            api_key = getattr(settings, "fmp_api_key", "")
            # ── Company profile ───────────────────────────────────────────
            _cache_key = ("fmp_profile", symbol)
            profile = _cache_get(_cache_key)
            if profile is None:
                with (start_span(trace, "provider_call", {"provider": "fmp", "op": "profile"})
                      if trace else _null_ctx()) as _sp:
                    profile = _governed_call(
                        "fmp",
                        fn       = lambda: get_company_profile(symbol, api_key=api_key),
                        has_key  = has_fmp_key,
                        scope    = scope,
                    )
                    if _sp: _sp.set_tag("symbol", symbol)
                if profile is not None:
                    _cache_set(_cache_key, profile)
            if profile:
                try:
                    ctx.company_profile = CompanyProfile(**{k: v for k, v in profile.items() if k in CompanyProfile.model_fields})  # type: ignore[arg-type]
                    filled_profile = True
                except Exception:
                    pass
            # ── Market snapshot ───────────────────────────────────────────
            _cache_key = ("fmp_snapshot", symbol)
            snapshot = _cache_get(_cache_key)
            if snapshot is None:
                with (start_span(trace, "provider_call", {"provider": "fmp", "op": "snapshot"})
                      if trace else _null_ctx()) as _sp:
                    snapshot = _governed_call(
                        "fmp",
                        fn      = lambda: get_market_snapshot(symbol, api_key=api_key),
                        has_key = has_fmp_key,
                        scope   = scope,
                    )
                if snapshot is not None:
                    _cache_set(_cache_key, snapshot)
            if snapshot:
                try:
                    ctx.market_snapshot = MarketSnapshot(**{k: v for k, v in snapshot.items() if k in MarketSnapshot.model_fields})  # type: ignore[arg-type]
                    filled_snapshot = True
                    if PriceRecord is not None and "price" in snapshot:
                        try:
                            ts = datetime.now(timezone.utc)
                            record = PriceRecord(ticker=symbol, timestamp=ts,
                                                 price=float(snapshot.get("price")),
                                                 volume=int(snapshot.get("volume")) if snapshot.get("volume") is not None else None)
                            insert_price_records([record])
                        except Exception:
                            pass
                except Exception:
                    pass
            # ── Financial context ─────────────────────────────────────────
            _cache_key = ("fmp_financial", symbol)
            fin = _cache_get(_cache_key)
            if fin is None:
                with (start_span(trace, "provider_call", {"provider": "fmp", "op": "financial"})
                      if trace else _null_ctx()) as _sp:
                    fin = _governed_call(
                        "fmp",
                        fn      = lambda: get_financial_context(symbol, api_key=api_key),
                        has_key = has_fmp_key,
                        scope   = scope,
                    )
                if fin is not None:
                    _cache_set(_cache_key, fin)
            if fin:
                try:
                    ctx.financial_context = FinancialContext(**{k: v for k, v in fin.items() if k in FinancialContext.model_fields})  # type: ignore[arg-type]
                    for k, v in fin.items():
                        try:
                            ctx.financials[k] = float(v)
                        except Exception:
                            pass
                    filled_financial = True
                    if FinancialRecord is not None:
                        try:
                            ts = datetime.now(timezone.utc)
                            fin_records = []
                            for metric_name, value in fin.items():
                                try:
                                    fin_records.append(FinancialRecord(ticker=symbol, timestamp=ts,
                                                                        metric_name=metric_name, value=float(value)))
                                except Exception:
                                    pass
                            if fin_records:
                                insert_financial_records(fin_records)
                        except Exception:
                            pass
                except Exception:
                    pass
            # ── Recent news ───────────────────────────────────────────────
            _cache_key = ("fmp_news", symbol)
            news = _cache_get(_cache_key)
            if news is None:
                with (start_span(trace, "provider_call", {"provider": "fmp", "op": "news"})
                      if trace else _null_ctx()) as _sp:
                    news = _governed_call(
                        "fmp",
                        fn      = lambda: get_recent_news(symbol, api_key=api_key, limit=3),
                        has_key = has_fmp_key,
                        scope   = scope,
                    )
                if news is not None:
                    _cache_set(_cache_key, news)
            if news:
                for item in news:
                    ctx.recent_events.append(f"{item['title']} ({item['date']})")
                ctx.source_notes.append("FMP press releases")
                if EventRecord is not None:
                    try:
                        ts = datetime.now(timezone.utc)
                        ev_records = [
                            EventRecord(ticker=symbol, timestamp=ts, event_type="news",
                                        description=f"{item.get('title','')} ({item.get('date','')})",
                                        source="FMP")
                            for item in news
                        ]
                        if ev_records:
                            insert_event_records(ev_records)
                    except Exception:
                        pass

        elif src == "sec":
            user_agent = getattr(settings, "sec_user_agent", "ai-analyst-bot/0.1")
            # ── SEC filings ───────────────────────────────────────────────
            _cache_key = ("sec_filings", symbol)
            filings = _cache_get(_cache_key)
            if filings is None:
                with (start_span(trace, "provider_call", {"provider": "sec", "op": "filings"})
                      if trace else _null_ctx()) as _sp:
                    filings = _governed_call(
                        "sec",
                        fn    = lambda: get_recent_filings(company, ticker=symbol, user_agent=user_agent, count=3),
                        scope = scope,
                    )
                if filings is not None:
                    _cache_set(_cache_key, filings)
            if filings:
                for item in filings:
                    try:
                        ctx.filings_context.append(FilingContext(**{k: v for k, v in item.items() if k in FilingContext.model_fields}))  # type: ignore[arg-type]
                    except Exception:
                        pass
                filled_filings = True
                ctx.source_notes.append("SEC EDGAR recent filings")
                if EventRecord is not None:
                    try:
                        ts = datetime.now(timezone.utc)
                        ev_records = []
                        for item in filings:
                            title = item.get("title", ""); date = item.get("filing_date", "")
                            desc  = f"{title} ({date})" if date else title
                            ev_records.append(EventRecord(ticker=symbol, timestamp=ts,
                                                           event_type="filing", description=desc, source="SEC"))
                        if ev_records:
                            insert_event_records(ev_records)
                    except Exception:
                        pass
            # ── SEC company facts ─────────────────────────────────────────
            _cache_key = ("sec_facts", symbol)
            facts = _cache_get(_cache_key)
            if facts is None:
                with (start_span(trace, "provider_call", {"provider": "sec", "op": "facts"})
                      if trace else _null_ctx()) as _sp:
                    facts = _governed_call(
                        "sec",
                        fn    = lambda: get_company_facts(symbol, user_agent=user_agent),
                        scope = scope,
                    )
                if facts is not None:
                    _cache_set(_cache_key, facts)
            if facts:
                if facts.get("entityName"):
                    ctx.known_facts.append(f"SEC lists entity name as {facts['entityName']}.")
                if facts.get("cik"):
                    ctx.known_facts.append(f"SEC lists CIK as {facts['cik']}.")
                if facts.get("ticker"):
                    ctx.known_facts.append(f"SEC lists ticker as {facts['ticker']}.")
                ctx.source_notes.append("SEC company facts")

        elif src == "retrieval":
            # ── Centralized retrieval via enterprise retrieval layer ───────
            # Route through enterprise retrieval module which normalizes,
            # deduplicates, ranks, and applies source governance.
            with (start_span(trace, "retrieval", {"provider": "retrieval"})
                  if trace else _null_ctx()) as _sp:
                if _ENTERPRISE:
                    try:
                        from ..enterprise.retrieval import RetrievalQuery, retrieve
                        ret_query = RetrievalQuery(
                            text        = question or company,
                            company     = company,
                            ticker      = ticker or "",
                            max_results = 6,
                        )
                        # Check scope-level source access for retrieval
                        if scope is None or scope.can_access_source("retrieval"):
                            ret_ctx = retrieve(ret_query, sources=["retrieval"])
                            for r in ret_ctx.results:
                                ctx.recent_events.append(r.title if r.title else r.snippet)
                            if ret_ctx.sources_used:
                                ctx.source_notes.append(f"Centralized retrieval (sources: {', '.join(ret_ctx.sources_used)})")
                            if _sp:
                                _sp.set_tag("result_count", len(ret_ctx.results))
                                _sp.set_tag("confidence", ret_ctx.confidence)
                        else:
                            logger.info("Retrieval blocked by scope restrictions")
                    except Exception as exc:
                        logger.warning(f"Enterprise retrieval failed, falling back: {exc}")
                        # Fallback to direct retrieval
                        _cache_key = ("retrieval_public", symbol)
                        public = _cache_get(_cache_key)
                        if public is None:
                            public = _governed_call("retrieval", fn=lambda: get_public_context(symbol, limit=3), scope=scope)
                            if public is not None:
                                _cache_set(_cache_key, public)
                        if public:
                            ctx.recent_events.extend(public)
                            ctx.source_notes.append("Public news retrieval")
                else:
                    # Non-enterprise fallback path
                    _cache_key = ("retrieval_public", symbol)
                    public = _cache_get(_cache_key)
                    if public is None:
                        public = _governed_call("retrieval", fn=lambda: get_public_context(symbol, limit=3), scope=scope)
                        if public is not None:
                            _cache_set(_cache_key, public)
                    if public:
                        ctx.recent_events.extend(public)
                        ctx.source_notes.append("Public news retrieval")
                    _cache_key = ("retrieval_doc", symbol)
                    doc_ctx = _cache_get(_cache_key)
                    if doc_ctx is None:
                        doc_ctx = _governed_call("retrieval", fn=lambda: get_document_context(question or company, limit=3), scope=scope)
                        if doc_ctx is not None:
                            _cache_set(_cache_key, doc_ctx)
                    if doc_ctx:
                        ctx.recent_events.extend(doc_ctx)
                        ctx.source_notes.append("Document context retrieval")

    # Placeholder enrichment for any fields that remain empty.  These
    # fallbacks mirror the logic in ``context_service.enrich_grounding_context``
    # but operate on the new structured fields.
    # Known facts placeholder
    if not ctx.known_facts:
        ctx.known_facts = [
            f"Key facts about {company} (industry, products, market share) were not provided."
        ]
    # Macro context placeholder
    if not ctx.macro_context:
        ctx.macro_context = [
            f"General macroeconomic factors such as inflation and interest rates may influence {company}."
        ]
    # Recent events placeholder when no events were added
    if not ctx.recent_events:
        ctx.recent_events = [f"No recent news or filings found for {company}."]
    # Source notes placeholder
    if not ctx.source_notes:
        ctx.source_notes = ["No external data sources were used."]
    # Ensure company profile exists
    if not filled_profile:
        ctx.company_profile = CompanyProfile()
    # Ensure market snapshot exists
    if not filled_snapshot:
        ctx.market_snapshot = MarketSnapshot()
    # Ensure financial context exists
    if not filled_financial:
        ctx.financial_context = FinancialContext()
    # Ensure filings context list exists (it does by default)
    if not filled_filings and not ctx.filings_context:
        ctx.filings_context = []
    return ctx
