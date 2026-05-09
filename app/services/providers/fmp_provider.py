"""
Financial Modeling Prep (FMP) evidence provider.

Fetches company-level financial data from the FMP REST API and converts it
into RetrievedEvidence objects for LLM prompt injection.

Requires the environment variable FMP_API_KEY.  Every public function returns
an empty list when the key is absent, the network is unreachable, or the API
returns an unexpected payload — callers never need to catch exceptions.

Capabilities
------------
search_ticker(company_name)          → best-matching ticker symbol (str)
fetch_company_profile(symbol)        → market cap, PE, price, sector / industry
fetch_price_change(symbol)           → 1-day through 1-year % changes
fetch_income_metrics(symbol)         → revenue, margins, earnings
fetch_debt_metrics(symbol)           → total debt, net debt, debt/equity
fetch_earnings_calendar(symbol)      → next / recent earnings dates + EPS estimates
fetch_company_evidence(company)      → top-level: calls all of the above
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import urlopen

from ...schemas import RetrievedEvidence

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Read FMP_API_KEY fresh from env each call (supports test monkeypatching)."""
    return os.environ.get("FMP_API_KEY", "").strip()


def _fetch_json(url: str, timeout: int = 8):
    """Fetch JSON from *url* via stdlib urllib.  Raises on any error."""
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_market_cap(value: Optional[float]) -> str:
    """Format a raw market-cap number as a human-readable string."""
    if not value:
        return "N/A"
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    return f"${value / 1e6:.0f}M"


def _fmt_pct(value: Optional[float]) -> str:
    """Format a ratio (0–1) as a percentage string."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _fmt_large(value: Optional[float]) -> str:
    """Format a large dollar amount in millions or billions."""
    if value is None:
        return "N/A"
    if abs(value) >= 1e9:
        return f"${value / 1e9:.2f}B"
    return f"${value / 1e6:.1f}M"


# ── Public provider functions ─────────────────────────────────────────────────

def search_ticker(company_name: str) -> str:
    """Search FMP for the best ticker match for *company_name*.

    Returns the first matching symbol string, or ``""`` on failure / no match.
    """
    api_key = _get_api_key()
    if not api_key:
        return ""
    params = urlencode({"query": company_name, "limit": 5, "apikey": api_key})
    url = f"{_FMP_BASE}/v3/search?{params}"
    try:
        data = _fetch_json(url)
        if data and isinstance(data, list) and data[0].get("symbol"):
            symbol = data[0]["symbol"]
            logger.debug("FMP ticker search '%s' → %s", company_name, symbol)
            return symbol
    except (HTTPError, URLError) as exc:
        logger.warning("FMP search network error for '%s': %r", company_name, exc)
    except Exception as exc:
        logger.warning("FMP search error for '%s': %r", company_name, exc)
    return ""


def fetch_company_profile(symbol: str) -> List[RetrievedEvidence]:
    """Fetch company profile: price, market cap, P/E, sector, industry."""
    api_key = _get_api_key()
    if not api_key or not symbol:
        return []
    url = f"{_FMP_BASE}/v3/profile/{quote(symbol)}?apikey={api_key}"
    try:
        data = _fetch_json(url)
        if not data or not isinstance(data, list):
            return []
        p = data[0]

        company_name  = p.get("companyName", symbol)
        price         = p.get("price")
        mkt_cap       = p.get("mktCap")
        pe            = p.get("pe")
        sector        = p.get("sector", "")
        industry      = p.get("industry", "")
        exchange      = p.get("exchangeShortName", "")
        beta          = p.get("beta")
        description   = p.get("description", "")
        ipo_date      = p.get("ipoDate", "")

        mc_str  = _fmt_market_cap(mkt_cap)
        pe_str  = f"{pe:.1f}" if pe else "N/A"
        price_s = f"${price:.2f}" if price else "N/A"

        title = (
            f"{company_name} ({symbol}) — "
            f"Price: {price_s} | Mkt Cap: {mc_str} | P/E: {pe_str}"
        )
        summary_parts = [
            f"{company_name} ({symbol}) trades on {exchange}.",
            f"Sector: {sector} / Industry: {industry}.",
            f"Current price: {price_s}.  Market cap: {mc_str}.  Trailing P/E: {pe_str}.",
        ]
        if beta is not None:
            summary_parts.append(f"Beta: {beta:.2f} (market sensitivity).")
        if description:
            summary_parts.append(description[:300])

        return [RetrievedEvidence(
            title=title,
            source="Financial Modeling Prep",
            summary=" ".join(summary_parts),
            timestamp=ipo_date,
            relevance_score=0.92,
        )]
    except (HTTPError, URLError) as exc:
        logger.warning("FMP profile network error for %s: %r", symbol, exc)
    except Exception as exc:
        logger.warning("FMP profile error for %s: %r", symbol, exc)
    return []


def fetch_price_change(symbol: str) -> List[RetrievedEvidence]:
    """Fetch stock price % changes across multiple time windows."""
    api_key = _get_api_key()
    if not api_key or not symbol:
        return []
    url = f"{_FMP_BASE}/v3/stock-price-change/{quote(symbol)}?apikey={api_key}"
    try:
        data = _fetch_json(url)
        if not data or not isinstance(data, list):
            return []
        p = data[0]

        def _chg(key: str) -> str:
            v = p.get(key)
            if v is None:
                return "N/A"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.2f}%"

        title = (
            f"{symbol} Price Change — "
            f"1D: {_chg('1D')}  |  1M: {_chg('1M')}  |  1Y: {_chg('1Y')}"
        )
        summary = (
            f"Recent {symbol} price performance: "
            f"1-day {_chg('1D')}, "
            f"5-day {_chg('5D')}, "
            f"1-month {_chg('1M')}, "
            f"3-month {_chg('3M')}, "
            f"6-month {_chg('6M')}, "
            f"YTD {_chg('ytd')}, "
            f"1-year {_chg('1Y')}."
        )
        return [RetrievedEvidence(
            title=title,
            source="Financial Modeling Prep",
            summary=summary,
            timestamp="",
            relevance_score=0.88,
        )]
    except (HTTPError, URLError) as exc:
        logger.warning("FMP price-change network error for %s: %r", symbol, exc)
    except Exception as exc:
        logger.warning("FMP price-change error for %s: %r", symbol, exc)
    return []


def fetch_income_metrics(symbol: str) -> List[RetrievedEvidence]:
    """Fetch revenue, gross margin, net margin, and EBITDA from the income statement."""
    api_key = _get_api_key()
    if not api_key or not symbol:
        return []
    params = urlencode({"limit": 2, "apikey": api_key})
    url = f"{_FMP_BASE}/v3/income-statement/{quote(symbol)}?{params}"
    try:
        data = _fetch_json(url)
        if not data or not isinstance(data, list):
            return []
        latest  = data[0]
        prior   = data[1] if len(data) > 1 else {}

        date          = latest.get("date", "")
        revenue       = latest.get("revenue")
        gross_margin  = latest.get("grossProfitRatio")
        net_margin    = latest.get("netIncomeRatio")
        ebitda        = latest.get("ebitda")

        prior_rev = prior.get("revenue")
        rev_growth = ""
        if revenue and prior_rev and prior_rev != 0:
            g = (revenue - prior_rev) / abs(prior_rev) * 100
            sign = "+" if g >= 0 else ""
            rev_growth = f" ({sign}{g:.1f}% YoY)"

        title = (
            f"{symbol} Financials — "
            f"Revenue: {_fmt_large(revenue)}{rev_growth} | "
            f"Gross Margin: {_fmt_pct(gross_margin)} | "
            f"Net Margin: {_fmt_pct(net_margin)}"
        )
        summary = (
            f"For the period ending {date}: "
            f"Revenue {_fmt_large(revenue)}{rev_growth}. "
            f"Gross profit margin {_fmt_pct(gross_margin)}. "
            f"Net income margin {_fmt_pct(net_margin)}. "
            f"EBITDA {_fmt_large(ebitda)}."
        )
        return [RetrievedEvidence(
            title=title,
            source="Financial Modeling Prep",
            summary=summary,
            timestamp=date,
            relevance_score=0.87,
        )]
    except (HTTPError, URLError) as exc:
        logger.warning("FMP income-statement network error for %s: %r", symbol, exc)
    except Exception as exc:
        logger.warning("FMP income-statement error for %s: %r", symbol, exc)
    return []


def fetch_debt_metrics(symbol: str) -> List[RetrievedEvidence]:
    """Fetch debt, cash, and leverage metrics from the balance sheet."""
    api_key = _get_api_key()
    if not api_key or not symbol:
        return []
    params = urlencode({"limit": 1, "apikey": api_key})
    url = f"{_FMP_BASE}/v3/balance-sheet-statement/{quote(symbol)}?{params}"
    try:
        data = _fetch_json(url)
        if not data or not isinstance(data, list):
            return []
        b = data[0]

        date      = b.get("date", "")
        total_debt = b.get("totalDebt")
        net_debt   = b.get("netDebt")
        cash       = b.get("cashAndCashEquivalents")
        de_ratio   = b.get("debtEquityRatio")

        de_str = f"{de_ratio:.2f}x" if de_ratio is not None else "N/A"
        title = (
            f"{symbol} Balance Sheet — "
            f"Total Debt: {_fmt_large(total_debt)} | "
            f"Net Debt: {_fmt_large(net_debt)} | "
            f"D/E: {de_str}"
        )
        summary = (
            f"As of {date}: "
            f"Total debt {_fmt_large(total_debt)}. "
            f"Cash & equivalents {_fmt_large(cash)}. "
            f"Net debt {_fmt_large(net_debt)}. "
            f"Debt-to-equity ratio {de_str}."
        )
        return [RetrievedEvidence(
            title=title,
            source="Financial Modeling Prep",
            summary=summary,
            timestamp=date,
            relevance_score=0.82,
        )]
    except (HTTPError, URLError) as exc:
        logger.warning("FMP balance-sheet network error for %s: %r", symbol, exc)
    except Exception as exc:
        logger.warning("FMP balance-sheet error for %s: %r", symbol, exc)
    return []


def fetch_earnings_calendar(symbol: str) -> List[RetrievedEvidence]:
    """Fetch recent / upcoming earnings dates and EPS estimates."""
    api_key = _get_api_key()
    if not api_key or not symbol:
        return []
    params = urlencode({"limit": 3, "apikey": api_key})
    url = f"{_FMP_BASE}/v3/historical/earning_calendar/{quote(symbol)}?{params}"
    try:
        data = _fetch_json(url)
        if not data or not isinstance(data, list):
            return []

        snippets = []
        for entry in data[:3]:
            date = entry.get("date", "")
            eps_est = entry.get("epsEstimated")
            eps_act = entry.get("eps")
            rev_est = entry.get("revenueEstimated")
            rev_act = entry.get("revenue")

            parts = [f"Date: {date}"]
            if eps_est is not None:
                parts.append(f"EPS estimate: ${eps_est:.2f}")
            if eps_act is not None:
                parts.append(f"EPS actual: ${eps_act:.2f}")
            if rev_est is not None:
                parts.append(f"Revenue estimate: {_fmt_large(rev_est)}")
            if rev_act is not None:
                parts.append(f"Revenue actual: {_fmt_large(rev_act)}")
            snippets.append("  •  ".join(parts))

        first = data[0]
        title = f"{symbol} Earnings — Next/Recent: {first.get('date', 'TBD')}"
        summary = f"Earnings calendar for {symbol}:\n" + "\n".join(snippets)
        return [RetrievedEvidence(
            title=title,
            source="Financial Modeling Prep",
            summary=summary,
            timestamp=first.get("date", ""),
            relevance_score=0.85,
        )]
    except (HTTPError, URLError) as exc:
        logger.warning("FMP earnings-calendar network error for %s: %r", symbol, exc)
    except Exception as exc:
        logger.warning("FMP earnings-calendar error for %s: %r", symbol, exc)
    return []


def fetch_company_evidence(company: str) -> List[RetrievedEvidence]:
    """Top-level entry point: resolve ticker then fetch all company evidence.

    Accepts either a ticker symbol (e.g. ``"AAPL"``) or a company name
    (e.g. ``"Apple Inc."``).  Tickers are detected by the heuristic:
    all-uppercase and ≤ 5 characters.

    Returns a combined, deduplicated list of RetrievedEvidence objects ready
    for prompt injection.  Returns ``[]`` when FMP_API_KEY is absent.
    """
    api_key = _get_api_key()
    if not api_key:
        print("[DIAG] FMP: FMP_API_KEY not set — skipping company evidence")
        return []

    company = company.strip()

    # Resolve ticker ──────────────────────────────────────────────────────────
    if company.upper() == company and len(company) <= 5:
        symbol = company          # looks like a ticker already
    else:
        symbol = search_ticker(company)
        if not symbol:
            logger.debug("FMP: no ticker found for '%s'", company)
            print(f"[DIAG] FMP: no ticker found for company '{company}'")
            return []

    print(f"[DIAG] FMP: fetching evidence for {symbol} (resolved from '{company}')")

    evidence: List[RetrievedEvidence] = []
    evidence.extend(fetch_company_profile(symbol))
    evidence.extend(fetch_price_change(symbol))
    evidence.extend(fetch_income_metrics(symbol))
    evidence.extend(fetch_debt_metrics(symbol))
    evidence.extend(fetch_earnings_calendar(symbol))

    print(f"[DIAG] FMP: {len(evidence)} evidence item(s) for {symbol}")
    return evidence
