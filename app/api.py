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
from pydantic import BaseModel

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


# ---------------------------------------------------------------------------
# Phase M — Real Market Infrastructure endpoints
# ---------------------------------------------------------------------------


@router.get("/pipeline/health", tags=["pipeline"])
async def get_pipeline_health() -> dict:
    """
    Return health status of all ingestion adapters.

    Reports per-adapter reachability, last run timestamp, dedup stats.
    """
    try:
        from .services.ingestion.event_ingestion_pipeline import get_default_pipeline
        pipeline = get_default_pipeline(auto_register=True)
        health = await pipeline.health_check()
        return health
    except Exception as exc:
        logger.warning("pipeline_health failed: %s", exc)
        return {"pipeline_healthy": False, "error": str(exc)}


class _PipelineRunRequest(BaseModel):
    tickers: Optional[list] = None
    since: Optional[str] = None


@router.post("/pipeline/run", tags=["pipeline"])
async def run_ingestion_pipeline(body: _PipelineRunRequest = None) -> dict:
    """
    Trigger a full ingestion pipeline run.

    Fetches from all registered adapters (SEC EDGAR, Treasury/Macro,
    Earnings, News), deduplicates, scores freshness, assesses thesis impact.

    Returns PipelineRunResult summary with impact assessments.
    """
    try:
        from .services.ingestion.event_ingestion_pipeline import get_default_pipeline
        pipeline = get_default_pipeline(auto_register=True)
        tickers = body.tickers if body else None
        since = body.since if body else None
        result = await pipeline.run(tickers=tickers, since=since)
        return {
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "duration_ms": result.duration_ms,
            "adapters_called": result.adapters_called,
            "events_fetched": result.events_fetched,
            "events_after_dedup": result.events_after_dedup,
            "events_after_freshness": result.events_after_freshness,
            "impact_assessments": [a.model_dump() for a in result.impact_assessments],
            "skipped_stale": result.skipped_stale,
            "adapter_errors": result.adapter_errors,
        }
    except Exception as exc:
        logger.warning("pipeline_run failed: %s", exc)
        return {"error": str(exc), "impact_assessments": []}


@router.post("/events/process", tags=["events"])
async def process_single_event(payload: dict) -> dict:
    """
    Process a single event through the LiveThesisUpdateService.

    Accepts a NormalizedEvent payload, runs through the full pipeline:
    normalize → thesis impact → regime update → watchlist drift.

    Returns UpdateSummary with per-ticker impact assessments.
    """
    try:
        from .services.ingestion.normalized_event import EventCategory, NormalizedEvent, SourceReliability
        from .services.live_thesis_update_service import get_live_thesis_service
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()

        # Build NormalizedEvent from payload with safe defaults
        event = NormalizedEvent(
            ticker=payload.get("ticker"),
            category=EventCategory(payload.get("category", "news")),
            headline=payload.get("headline", ""),
            body=payload.get("body", ""),
            source=payload.get("source", "api"),
            source_reliability=SourceReliability(
                payload.get("source_reliability", "medium")
            ),
            event_timestamp=payload.get("event_timestamp") or now_iso,
            ingestion_timestamp=now_iso,
            is_market_moving=payload.get("is_market_moving", False),
            tags=payload.get("tags", []),
            magnitude=payload.get("magnitude"),
        )

        service = get_live_thesis_service()
        summary = service.process_event(event)
        return summary.to_dict()
    except Exception as exc:
        logger.warning("process_single_event failed: %s", exc)
        return {"error": str(exc), "impact_count": 0}


@router.get("/events/freshness/{ticker}", tags=["events"])
async def get_event_freshness(ticker: str, limit: int = 20) -> list:
    """
    Return recent EventImpactAssessments with freshness scores for a ticker.

    Adds freshness metadata (age_hours, label, is_stale) to each assessment.
    Used by the frontend to display "Live / Today / This Week / Stale" labels.
    """
    try:
        from .services.timeline_store import default_store
        from .services.ingestion.freshness_scorer import freshness_label
        from datetime import datetime, timezone

        entries = default_store.load(ticker.upper(), entry_type="event_impact")
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        now = datetime.now(timezone.utc)
        result = []
        for entry in entries[:limit]:
            data = dict(entry.data)
            # Add freshness metadata based on assessment timestamp
            ts_str = data.get("timestamp", "") or entry.timestamp or ""
            age_hours = 999.0
            if ts_str:
                try:
                    ts_str_clean = ts_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(ts_str_clean)
                    if dt.tzinfo is None:
                        from datetime import timezone as tz
                        dt = dt.replace(tzinfo=tz.utc)
                    age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
                except Exception:
                    pass
            data["freshness_label"] = freshness_label(age_hours)
            data["age_hours"] = round(age_hours, 1)
            result.append(data)
        return result
    except Exception as exc:
        logger.warning("get_event_freshness failed: %s", exc)
        return []


@router.get("/morning-brief/v2", tags=["brief"])
async def get_morning_brief_v2(reference_date: Optional[str] = None) -> dict:
    """
    Generate the Phase M 5-section institutional morning brief.

    Sections:
      1. Market Regime (rate_environment, risk_appetite, regime_headline)
      2. What Changed (narrative_shifts — 2-4 PM sentences)
      3. Debate Shifts (debate_shifts — 2-3 sentences)
      4. Priority Alerts (priority_alerts + attention_required tickers)
      5. Watchlist Drift (per-ticker direction/driver/materiality)
    """
    try:
        from .services.watchlist_service import watchlist_service
        from .services.market_regime_tracker import get_current_regime
        from .services.thesis_impact_evaluator import get_default_evaluator
        from .services.morning_brief_service import generate_morning_brief_v2
        from .services.timeline_store import default_store

        # Fetch watchlist state
        watchlist_entries = await watchlist_service.get_all_entries()

        # Fetch current regime
        try:
            regime = get_current_regime()
        except Exception:
            regime = None

        # Fetch recent event impacts across all watched tickers
        all_impacts = []
        for entry in watchlist_entries:
            ticker_entries = default_store.load(entry.ticker, entry_type="event_impact")
            ticker_entries.sort(key=lambda e: e.timestamp, reverse=True)
            from .schemas import EventImpactAssessment
            for te in ticker_entries[:5]:
                try:
                    all_impacts.append(EventImpactAssessment.model_validate(te.data))
                except Exception:
                    pass

        # Compute watchlist drift
        evaluator = get_default_evaluator()
        tickers = [e.ticker for e in watchlist_entries]
        drift = evaluator.get_watchlist_drift(tickers) if tickers else []

        brief = generate_morning_brief_v2(
            watchlist_entries=watchlist_entries,
            event_impacts=all_impacts,
            watchlist_drift=drift,
            regime=regime,
            reference_date=reference_date,
        )
        return brief.model_dump()
    except Exception as exc:
        logger.warning("morning_brief_v2 failed: %s", exc)
        return {"error": str(exc), "regime_headline": "", "narrative_shifts": []}


@router.get("/watchlist/drift", tags=["watchlist"])
async def get_watchlist_drift() -> list:
    """
    Return current thesis drift summaries for all watched tickers.

    Sorted by materiality descending. Direction: broke > weakened > strengthened > unchanged.
    Used by the watchlist page to show thesis evolution without running a full analysis.
    """
    try:
        from .services.watchlist_service import watchlist_service
        from .services.thesis_impact_evaluator import get_default_evaluator

        entries = await watchlist_service.get_all_entries()
        tickers = [e.ticker for e in entries]
        evaluator = get_default_evaluator()
        drift = evaluator.get_watchlist_drift(tickers)
        return [d.model_dump() for d in drift]
    except Exception as exc:
        logger.warning("watchlist_drift failed: %s", exc)
        return []
