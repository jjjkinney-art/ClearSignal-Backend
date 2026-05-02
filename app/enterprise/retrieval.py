"""
Centralized retrieval abstraction layer.

All retrieval operations — public web, document search, internal
lookups — route through this module.  No retrieval logic should be
scattered across individual provider modules.

Capabilities
------------
- Unified RetrievalQuery / RetrievalResult types
- Freshness / recency scoring
- Result normalization and deduplication
- Ranking / reranking hook (pluggable)
- Citation / source metadata normalization
- Graceful fallback on partial or total retrieval failure
- Per-source result caps

Usage::

    query  = RetrievalQuery(text="Apple earnings outlook", max_results=5)
    ctx    = retrieve(query, sources=["retrieval", "sec"])
    for r in ctx.results:
        print(r.title, r.relevance_score, r.source)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────────────

@dataclass
class RetrievalQuery:
    """Describes what to retrieve.

    Attributes
    ----------
    text            : natural-language query string
    company         : optional company name to filter results
    ticker          : optional ticker to filter results
    max_results     : max results to return in total
    max_per_source  : cap per source (prevents one source dominating)
    require_fresh   : if True, deprioritize results older than fresh_days
    fresh_days      : number of days to consider "fresh"
    source_filter   : explicit list of source names to include
    """
    text:           str
    company:        str = ""
    ticker:         str = ""
    max_results:    int = 10
    max_per_source: int = 5
    require_fresh:  bool = False
    fresh_days:     int  = 30
    source_filter:  List[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    """A single normalized retrieval result.

    Attributes
    ----------
    source          : provider/source name
    title           : result title
    snippet         : short excerpt or description
    url             : source URL if available
    date            : publication date string (ISO if available)
    relevance_score : 0.0–1.0 relevance to query
    freshness_score : 0.0–1.0 freshness (1.0 = today)
    combined_score  : weighted combination for ranking
    metadata        : additional source-specific metadata
    """
    source:          str
    title:           str
    snippet:         str = ""
    url:             str = ""
    date:            str = ""
    relevance_score: float = 0.5
    freshness_score: float = 1.0
    combined_score:  float = 0.5
    metadata:        Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalContext:
    """Full retrieval response for a query.

    Attributes
    ----------
    query           : the original query
    results         : normalized, ranked results
    sources_used    : which sources were actually queried
    sources_failed  : sources that failed
    fallback_used   : whether a fallback path was activated
    latency_ms      : total retrieval time
    confidence      : 0.0–1.0 confidence in result quality
    """
    query:          RetrievalQuery
    results:        List[RetrievalResult] = field(default_factory=list)
    sources_used:   List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    fallback_used:  bool  = False
    latency_ms:     float = 0.0
    confidence:     float = 1.0


# ── Freshness scoring ─────────────────────────────────────────────────────

def _freshness_score(date_str: str, fresh_days: int = 30) -> float:
    """Return a 0.0–1.0 freshness score.  1.0 = today, 0.0 = very old."""
    if not date_str:
        return 0.5   # unknown date → neutral
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
        if age_days < 0:
            return 1.0
        score = max(0.0, 1.0 - (age_days / max(fresh_days * 3, 90)))
        return score
    except Exception:
        return 0.5


# ── Result normalization ──────────────────────────────────────────────────

def _normalize(raw: Dict[str, Any], source: str) -> RetrievalResult:
    """Normalize a raw provider response dict into a RetrievalResult."""
    # Try common field names across providers
    title   = raw.get("title") or raw.get("name") or raw.get("filing_type") or "Untitled"
    snippet = (raw.get("snippet") or raw.get("description") or
               raw.get("text") or raw.get("summary") or "")
    url     = raw.get("url") or raw.get("link") or raw.get("filing_url") or ""
    date    = (raw.get("date") or raw.get("published") or
               raw.get("filing_date") or raw.get("timestamp") or "")

    relevance = float(raw.get("relevance", 0.5))
    freshness = _freshness_score(date)

    return RetrievalResult(
        source          = source,
        title           = str(title)[:256],
        snippet         = str(snippet)[:512],
        url             = str(url)[:512],
        date            = str(date)[:64],
        relevance_score = min(1.0, max(0.0, relevance)),
        freshness_score = freshness,
        combined_score  = 0.6 * relevance + 0.4 * freshness,
        metadata        = {k: v for k, v in raw.items()
                           if k not in ("title","name","snippet","description","text","url","date")},
    )


# ── Ranking hook ─────────────────────────────────────────────────────────

# Default ranker: sort by combined_score descending
_RERANK_HOOK: Optional[Callable[[List[RetrievalResult], RetrievalQuery], List[RetrievalResult]]] = None


def set_rerank_hook(hook: Callable[[List[RetrievalResult], RetrievalQuery], List[RetrievalResult]]) -> None:
    """Register a custom reranker.  Called after normalization, before truncation."""
    global _RERANK_HOOK
    _RERANK_HOOK = hook


def _rank(results: List[RetrievalResult], query: RetrievalQuery) -> List[RetrievalResult]:
    if _RERANK_HOOK is not None:
        try:
            return _RERANK_HOOK(results, query)
        except Exception as exc:
            logger.warning(f"Rerank hook failed: {exc}")
    return sorted(results, key=lambda r: r.combined_score, reverse=True)


# ── Deduplication ─────────────────────────────────────────────────────────

def _deduplicate(results: List[RetrievalResult]) -> List[RetrievalResult]:
    """Remove near-duplicate titles (case-insensitive first 80 chars)."""
    seen: set = set()
    out: List[RetrievalResult] = []
    for r in results:
        key = r.title.lower()[:80].strip()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ── Source adapters ───────────────────────────────────────────────────────

def _fetch_from_retrieval(query: RetrievalQuery) -> List[RetrievalResult]:
    """Fetch from the existing retrieval_provider."""
    results: List[RetrievalResult] = []
    try:
        from ..providers.retrieval_provider import get_public_context, get_document_context
        raw_public = get_public_context(query.company or query.text) or []
        for item in raw_public[:query.max_per_source]:
            if isinstance(item, dict):
                results.append(_normalize(item, "retrieval"))
            elif isinstance(item, str):
                results.append(RetrievalResult(
                    source="retrieval", title=item[:128], snippet=item,
                    relevance_score=0.5, freshness_score=0.5, combined_score=0.5,
                ))
        raw_doc = get_document_context(query.company or query.text) or []
        for item in raw_doc[:query.max_per_source]:
            if isinstance(item, dict):
                results.append(_normalize(item, "retrieval_doc"))
            elif isinstance(item, str):
                results.append(RetrievalResult(
                    source="retrieval_doc", title=item[:128], snippet=item,
                    relevance_score=0.5, freshness_score=0.5, combined_score=0.5,
                ))
    except Exception as exc:
        logger.warning(f"retrieval fetch failed: {exc}")
    return results


def _fetch_from_sec(query: RetrievalQuery) -> List[RetrievalResult]:
    """Fetch from the existing SEC client."""
    results: List[RetrievalResult] = []
    try:
        from ..providers.sec_client import get_recent_filings
        raw = get_recent_filings(query.ticker or query.company) or []
        for item in raw[:query.max_per_source]:
            if isinstance(item, dict):
                results.append(_normalize(item, "sec"))
    except Exception as exc:
        logger.warning(f"sec fetch failed: {exc}")
    return results


def _fetch_from_news(query: RetrievalQuery) -> List[RetrievalResult]:
    """Fetch news from FMP."""
    results: List[RetrievalResult] = []
    try:
        from ..providers.fmp_client import get_recent_news
        from ..config import settings
        raw = get_recent_news(query.ticker or query.company, api_key=settings.fmp_api_key) or []
        for item in raw[:query.max_per_source]:
            if isinstance(item, dict):
                results.append(_normalize(item, "fmp_news"))
    except Exception as exc:
        logger.warning(f"fmp news fetch failed: {exc}")
    return results


# Source dispatcher
_SOURCE_ADAPTERS: Dict[str, Callable[[RetrievalQuery], List[RetrievalResult]]] = {
    "retrieval": _fetch_from_retrieval,
    "sec":       _fetch_from_sec,
    "fmp_news":  _fetch_from_news,
}


# ── Primary entry point ───────────────────────────────────────────────────

def retrieve(
    query: RetrievalQuery,
    sources: Optional[List[str]] = None,
) -> RetrievalContext:
    """Execute a retrieval query across the specified sources.

    Normalizes, deduplicates, ranks, and truncates results.
    Returns a RetrievalContext with confidence degradation if sources fail.
    """
    t_start       = time.time()
    active_sources = sources or list(_SOURCE_ADAPTERS.keys())
    if query.source_filter:
        active_sources = [s for s in active_sources if s in query.source_filter]

    all_results:    List[RetrievalResult] = []
    sources_used:   List[str] = []
    sources_failed: List[str] = []

    for src in active_sources:
        adapter = _SOURCE_ADAPTERS.get(src)
        if adapter is None:
            logger.debug(f"No adapter for source '{src}', skipping")
            continue
        try:
            raw_results = adapter(query)
            if raw_results:
                all_results.extend(raw_results)
                sources_used.append(src)
        except Exception as exc:
            logger.warning(f"Retrieval source '{src}' failed: {exc}")
            sources_failed.append(src)

    # Freshness filter
    if query.require_fresh:
        all_results = [
            r for r in all_results
            if r.freshness_score >= (1.0 - query.fresh_days / 90.0)
        ] or all_results   # fall back to all if filter eliminates everything

    # Normalize, deduplicate, rank, truncate
    all_results = _deduplicate(all_results)
    all_results = _rank(all_results, query)
    all_results = all_results[:query.max_results]

    # Confidence degrades with source failures
    if not sources_used:
        confidence = 0.0
    elif sources_failed:
        confidence = len(sources_used) / (len(sources_used) + len(sources_failed))
    else:
        confidence = 1.0

    latency_ms = (time.time() - t_start) * 1000
    fallback_used = len(sources_failed) > 0 and len(sources_used) > 0

    return RetrievalContext(
        query         = query,
        results       = all_results,
        sources_used  = sources_used,
        sources_failed = sources_failed,
        fallback_used = fallback_used,
        latency_ms    = latency_ms,
        confidence    = confidence,
    )
