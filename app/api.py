from __future__ import annotations

"""
FastAPI routes for the AI analyst backend.

Defines endpoints for health checking and company analysis. The
analysis endpoint uses the service layer to orchestrate agent
execution and returns a structured response.

Enterprise lifecycle:
    The /analyze endpoint extracts X-Request-ID, X-Session-ID, X-User-ID,
    and X-Tenant-ID headers and builds a ScopeContext that is propagated
    through the full analysis lifecycle (evidence, agents, monitoring,
    alerts).
"""

import logging
from typing import Optional

import requests as _requests
from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import (
    AnalysisRequest,
    AnalysisResponse,
    QuestionRequest,
    AgentAnswerResponse,
    WatchlistEntry,
    ThesisSnapshot,
    ThesisDiff,
    MaterialChangeEvent,
)
from .services.analysis_service import analyze_company
from .services.router_service import route_question
from .services.watchlist_service import watchlist_service

logger = logging.getLogger(__name__)

# Enterprise scope extraction
try:
    from .enterprise.tenant import ScopeContext, TenantScope, UserScope, register_scope
    _API_ENTERPRISE = True
except Exception:
    _API_ENTERPRISE = False


router = APIRouter()


def _extract_scope(request: Request) -> "ScopeContext | None":
    """Extract tenant/user scope from standard enterprise HTTP headers.

    Headers consumed:
        X-Request-ID  : client-assigned request identifier
        X-Session-ID  : session identifier for correlation
        X-User-ID     : authenticated user identifier
        X-Tenant-ID   : tenant/organization identifier
    """
    if not _API_ENTERPRISE:
        return None
    try:
        headers    = request.headers
        user_id    = headers.get("X-User-ID",   "")
        tenant_id  = headers.get("X-Tenant-ID", "")
        session_id = headers.get("X-Session-ID", headers.get("X-Request-ID", ""))
        if not (user_id or tenant_id or session_id):
            return None
        scope = ScopeContext(
            user_id    = user_id,
            tenant_id  = tenant_id,
            session_id = session_id,
        )
        if session_id:
            register_scope(scope)
        return scope
    except Exception:
        return None


@router.get("/health", summary="Health check", tags=["health"])
async def health() -> dict:
    """Return basic health status."""
    return {"status": "ok"}


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    summary="Analyze a company",
    tags=["analysis"],
)
async def analyze(request: AnalysisRequest, http_request: Request) -> AnalysisResponse:
    """Perform an AI analysis of the requested company.

    Enterprise lifecycle:
        - Scope is extracted from HTTP headers and passed into analyze_company
        - The full analysis flow (evidence, agents, synthesis, monitoring, alerts)
          runs under enterprise governance with the resolved scope.
    """
    try:
        scope = _extract_scope(http_request)
        return analyze_company(request, scope=scope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Analysis failed to complete") from exc


@router.post(
    "/ask",
    response_model=AgentAnswerResponse,
    summary="Ask a question to a specialist agent",
    tags=["questions"],
)
async def ask_question(request: QuestionRequest) -> AgentAnswerResponse:
    """Route a user question to the appropriate agent and return its answer."""
    try:
        return route_question(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Question routing failed") from exc


# ── Exchange short-name normalisation ─────────────────────────────────────────
_EXCHANGE_MAP = {
    "NASDAQ Global Select":    "NASDAQ",
    "NASDAQ Global Market":    "NASDAQ",
    "NASDAQ Capital Market":   "NASDAQ",
    "New York Stock Exchange": "NYSE",
    "NYSE American":           "AMEX",
    "NYSE Arca":               "AMEX",
    "Tokyo Stock Exchange":    "TSE",
    "London Stock Exchange":   "LSE",
    "Euronext Amsterdam":      "EURONEXT",
    "Euronext Paris":          "EURONEXT",
}


def _normalise_exchange(raw: Optional[str]) -> str:
    if not raw:
        return "NYSE"
    return _EXCHANGE_MAP.get(raw, raw)


def _fmp_get(url: str) -> Optional[list | dict]:
    """Minimal HTTP helper — returns None on any failure."""
    try:
        r = _requests.get(url, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("FMP request failed: %s", exc)
        return None


@router.get(
    "/market/resolve",
    summary="Resolve company name/ticker to exchange symbol and market data",
    tags=["market"],
)
async def market_resolve(
    query: str = Query(..., description="Company name or ticker to resolve"),
) -> dict:
    """Resolve a company name or ticker to its exchange symbol.

    Returns resolved symbol information and optional real-time market data
    when FMP_API_KEY is configured.  Fields that cannot be populated are
    omitted from the response — the frontend must handle missing fields
    gracefully and must not display placeholder values.
    """
    from .config import settings

    api_key = settings.fmp_api_key
    base    = "https://financialmodelingprep.com/api/v3"

    ticker: Optional[str]   = None
    name:   Optional[str]   = None
    exchange: Optional[str] = None

    # ── Step 1: FMP symbol search ──────────────────────────────────────────
    search_url = f"{base}/search?query={_requests.utils.quote(query)}&limit=5"
    if api_key:
        search_url += f"&apikey={api_key}"
    search_data = _fmp_get(search_url)
    if search_data and isinstance(search_data, list) and search_data:
        top        = search_data[0]
        ticker     = top.get("symbol")
        name       = top.get("name")
        exchange   = _normalise_exchange(
            top.get("stockExchange") or top.get("exchangeShortName")
        )

    if not ticker:
        return {"query": query, "error": "Symbol could not be resolved"}

    tv_symbol = f"{exchange}:{ticker}" if exchange else ticker

    result: dict = {
        "query":             query,
        "name":              name,
        "ticker":            ticker,
        "exchange":          exchange,
        "tradingViewSymbol": tv_symbol,
    }

    # ── Step 2: real-time quote (only when API key present) ────────────────
    if api_key:
        quote_url  = f"{base}/quote/{ticker}?apikey={api_key}"
        quote_data = _fmp_get(quote_url)
        if quote_data and isinstance(quote_data, list) and quote_data:
            q_rec = quote_data[0]
            def _safe_float(val) -> Optional[float]:
                try:
                    return float(val) if val is not None else None
                except (TypeError, ValueError):
                    return None

            price           = _safe_float(q_rec.get("price"))
            change_pct      = _safe_float(q_rec.get("changesPercentage"))
            market_cap      = _safe_float(q_rec.get("marketCap"))
            volume          = q_rec.get("volume")
            high_52         = _safe_float(q_rec.get("yearHigh"))
            low_52          = _safe_float(q_rec.get("yearLow"))
            pe              = _safe_float(q_rec.get("pe"))

            if price           is not None: result["price"]            = price
            if change_pct      is not None: result["changePercent"]    = change_pct
            if market_cap      is not None: result["marketCap"]        = market_cap
            if volume          is not None: result["volume"]           = volume
            if high_52         is not None: result["fiftyTwoWeekHigh"] = high_52
            if low_52          is not None: result["fiftyTwoWeekLow"]  = low_52
            if pe              is not None: result["peRatio"]          = pe

    return result


# =============================================================================
# WATCHLIST ENDPOINTS
# =============================================================================


@router.get(
    "/watchlist",
    response_model=list,
    summary="List all watchlisted tickers",
    tags=["watchlist"],
)
async def get_watchlist() -> list:
    """Return all watchlist entries sorted by most-recently-added."""
    return [e.model_dump() for e in watchlist_service.get_watchlist()]


@router.post(
    "/watchlist/{ticker}",
    response_model=dict,
    summary="Add a ticker to the watchlist",
    tags=["watchlist"],
)
async def add_to_watchlist(
    ticker:       str,
    company_name: str = Query(default="", description="Optional canonical company name"),
) -> dict:
    """Add *ticker* to the watchlist.  Idempotent — safe to call multiple times."""
    entry = watchlist_service.add_ticker(ticker, company_name)
    return entry.model_dump()


@router.delete(
    "/watchlist/{ticker}",
    response_model=dict,
    summary="Remove a ticker from the watchlist",
    tags=["watchlist"],
)
async def remove_from_watchlist(ticker: str) -> dict:
    """Remove *ticker* from the watchlist.  Returns {removed: bool}."""
    removed = watchlist_service.remove_ticker(ticker)
    return {"ticker": ticker.upper(), "removed": removed}


@router.get(
    "/watchlist/{ticker}/snapshots",
    response_model=list,
    summary="Get thesis snapshot history for a ticker",
    tags=["watchlist"],
)
async def get_snapshots(
    ticker: str,
    limit:  int = Query(default=20, ge=1, le=200, description="Max snapshots to return"),
) -> list:
    """Return the thesis snapshot history for *ticker*, newest-first."""
    snaps = watchlist_service.get_snapshots(ticker, limit=limit)
    return [s.model_dump() for s in snaps]


@router.get(
    "/watchlist/{ticker}/diff",
    response_model=dict,
    summary="Get the latest thesis diff for a ticker",
    tags=["watchlist"],
)
async def get_latest_diff(ticker: str) -> dict:
    """Return the diff between the two most recent snapshots for *ticker*.

    Returns {available: false} when fewer than two snapshots exist.
    """
    diff = watchlist_service.get_latest_diff(ticker)
    if diff is None:
        return {"available": False, "ticker": ticker.upper()}
    return {"available": True, "ticker": ticker.upper(), **diff.model_dump()}


@router.get(
    "/watchlist/changes/material",
    response_model=list,
    summary="Get material change events across all watchlisted tickers",
    tags=["watchlist"],
)
async def get_material_changes(
    limit: int = Query(default=50, ge=1, le=500, description="Max events to return"),
) -> list:
    """Return the most recent material change events across the entire watchlist."""
    events = watchlist_service.get_material_changes(limit=limit)
    return [e.model_dump() for e in events]


@router.get(
    "/watchlist/{ticker}/changes",
    response_model=list,
    summary="Get material change events for a specific ticker",
    tags=["watchlist"],
)
async def get_ticker_changes(
    ticker: str,
    limit:  int = Query(default=20, ge=1, le=200),
) -> list:
    """Return material change events for *ticker*, newest-first."""
    events = watchlist_service.get_material_changes(ticker=ticker, limit=limit)
    return [e.model_dump() for e in events]


@router.post(
    "/watchlist/{ticker}/acknowledge",
    response_model=dict,
    summary="Clear the material-change flag for a ticker",
    tags=["watchlist"],
)
async def acknowledge_change(ticker: str) -> dict:
    """Mark the material-change alert as reviewed for *ticker*."""
    watchlist_service.clear_material_change_flag(ticker)
    return {"ticker": ticker.upper(), "acknowledged": True}


@router.get(
    "/alerts",
    response_model=list,
    summary="Get real-time thesis alerts from material change events",
    tags=["watchlist"],
)
async def get_alerts(
    limit: int = Query(default=30, ge=1, le=200, description="Max alerts to return"),
) -> list:
    """Return material change events formatted as analyst alerts, newest-first.

    Each alert includes: ticker, headline, summary, severity, timestamp, change_type.
    Backed by the persistent MaterialChangeEvent store — only returns real events
    from actual thesis analyses. Returns empty list when no events exist.
    """
    events = watchlist_service.get_material_changes(limit=limit)
    alerts = []
    for ev in events:
        # Format timestamp for display
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
            ts_display = dt.strftime("%b %d · %H:%M")
        except Exception:
            ts_display = ev.timestamp[:16] if ev.timestamp else "—"

        alerts.append({
            "id":          ev.event_id,
            "ticker":      ev.ticker,
            "headline":    ev.summary,
            "summary":     _build_alert_body(ev),
            "severity":    ev.severity,
            "timestamp":   ts_display,
            "change_type": ev.change_type,
        })
    return alerts


def _build_alert_body(ev) -> str:
    """Build a contextual alert body from a MaterialChangeEvent."""
    parts = []
    if ev.drivers:
        # First driver as context
        parts.append(ev.drivers[0])
    if ev.confidence_change and abs(ev.confidence_change) >= 0.04:
        direction = "improved" if ev.confidence_change > 0 else "weakened"
        parts.append(f"Conviction {direction} since the prior analysis.")
    if not parts:
        parts.append("Review the updated thesis for full context.")
    return " ".join(parts)


# =============================================================================
# PHASE I ENDPOINTS
# =============================================================================


@router.get(
    "/morning-brief",
    response_model=dict,
    summary="Generate a morning brief from current watchlist state",
    tags=["intelligence"],
)
async def get_morning_brief() -> dict:
    """Generate a PM-style morning brief from current watchlist state.

    Includes a compressed narrative, top movers, attention-required tickers,
    and a market regime note.  Deterministic — no LLM calls.
    """
    from .services.morning_brief_service import generate_morning_brief

    entries  = watchlist_service.get_watchlist()
    changes  = watchlist_service.get_material_changes(limit=100)
    brief    = generate_morning_brief(
        watchlist_entries=entries,
        recent_material_changes=changes,
        recent_alerts=[],
    )
    return brief.model_dump()


@router.get(
    "/timeline-events/{ticker}",
    response_model=list,
    summary="Get structured timeline events for a ticker",
    tags=["intelligence"],
)
async def get_timeline_events(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list:
    """Return structured TimelineEvent objects for *ticker*, newest-first.

    Converts stored material change events and thesis diffs into
    frontend-ready timeline entries.
    """
    from .services.timeline_event_service import get_ticker_timeline

    events = get_ticker_timeline(ticker, limit=limit)
    return [e.model_dump() for e in events]


@router.get(
    "/alert-priority/{ticker}",
    response_model=dict,
    summary="Get the priority level of the most recent alert for a ticker",
    tags=["intelligence"],
)
async def get_alert_priority(ticker: str) -> dict:
    """Return the AlertPriority for the most recent thesis diff for *ticker*.

    Returns {available: false} when no diff exists.
    """
    from .services.alert_prioritizer import alert_priority_score

    diff         = watchlist_service.get_latest_diff(ticker)
    latest_event = watchlist_service.get_material_changes(ticker=ticker, limit=1)
    event        = latest_event[0] if latest_event else None

    if diff is None:
        return {"available": False, "ticker": ticker.upper()}

    ap = alert_priority_score(diff, event)
    return {"available": True, "ticker": ticker.upper(), **ap.model_dump()}


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", tags=["history"])
async def get_history(
    ticker: Optional[str] = None,
    limit: int = 50,
) -> list:
    """Return analysis history, optionally filtered by ticker."""
    from .services.history_service import get_analysis_history
    try:
        entries = get_analysis_history(ticker=ticker, limit=limit)
        return [e.model_dump() for e in entries]
    except Exception as exc:
        logger.warning("get_history failed: %s", exc)
        return []

@router.get("/history/summary", tags=["history"])
async def get_history_summary_endpoint() -> dict:
    """Return a summary of tracked history."""
    from .services.history_service import get_history_summary
    try:
        return get_history_summary()
    except Exception as exc:
        logger.warning("get_history_summary failed: %s", exc)
        return {"total_tickers": 0, "total_entries": 0}

@router.get("/watchlist/themes", tags=["watchlist"])
async def get_watchlist_themes() -> list:
    """Return watchlist entries grouped by macro theme."""
    from .services.watchlist_themes import group_watchlist_by_theme
    try:
        entries = watchlist_service.get_watchlist()
        raw = [e.model_dump() for e in entries]
        groups = group_watchlist_by_theme(raw)
        return [g.model_dump() for g in groups]
    except Exception as exc:
        logger.warning("get_watchlist_themes failed: %s", exc)
        return []

@router.get("/usage/stats", tags=["usage"])
async def get_usage_stats() -> dict:
    """Return aggregate usage statistics."""
    from .services.usage_tracking import usage_tracker
    return usage_tracker.get_totals()


# ── Live Market Intelligence (Phase L) ───────────────────────────────────────

@router.post("/events/ingest", tags=["events"])
async def ingest_event(event_data: dict) -> dict:
    """
    Ingest a normalized event and return impact assessments for all relevant tickers.
    Accepts NormalizedEvent-compatible dict.
    """
    from .services.ingestion.normalized_event import NormalizedEvent, EventCategory, SourceReliability
    from .services.event_processor import process_event_for_watchlist, save_impact_assessment
    from .services.market_regime_tracker import update_regime
    try:
        # Normalize event_data
        event = NormalizedEvent(**{
            k: v for k, v in event_data.items()
            if k in NormalizedEvent.model_fields
        })
        impacts = process_event_for_watchlist(event)
        # Save all non-noise impacts
        for impact in impacts:
            save_impact_assessment(impact)
        # Update regime if this is a macro event
        if event.category == EventCategory.MACRO:
            update_regime([event])
        return {
            "event_id": event.event_id,
            "ticker": event.ticker,
            "impact_count": len(impacts),
            "impacts": [i.model_dump() for i in impacts],
        }
    except Exception as exc:
        logger.warning("ingest_event failed: %s", exc)
        return {"error": str(exc), "impact_count": 0, "impacts": []}


@router.get("/events/impact/{ticker}", tags=["events"])
async def get_event_impacts(ticker: str, limit: int = 20) -> list:
    """Get recent event impact assessments for a specific ticker."""
    try:
        from .services.timeline_store import default_store
        entries = default_store.load(ticker.upper(), entry_type="event_impact")
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return [e.data for e in entries[:limit]]
    except Exception as exc:
        logger.warning("get_event_impacts failed: %s", exc)
        return []


@router.get("/regime", tags=["market"])
async def get_market_regime() -> dict:
    """Get the current market regime classification."""
    from .services.market_regime_tracker import get_current_regime
    try:
        regime = get_current_regime()
        return regime.model_dump()
    except Exception as exc:
        logger.warning("get_market_regime failed: %s", exc)
        return {"rate_environment": "uncertain", "risk_appetite": "selective"}
