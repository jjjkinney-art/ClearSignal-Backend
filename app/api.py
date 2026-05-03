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

from .schemas import AnalysisRequest, AnalysisResponse, QuestionRequest, AgentAnswerResponse
from .services.analysis_service import analyze_company
from .services.router_service import route_question

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
