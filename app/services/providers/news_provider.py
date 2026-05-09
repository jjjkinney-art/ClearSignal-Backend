"""
NewsAPI evidence provider.

Fetches recent news headlines from the NewsAPI.org REST API and converts them
into RetrievedEvidence objects for LLM prompt injection.

Requires the environment variable NEWS_API_KEY.  Every public function returns
an empty list when the key is absent, the plan limits are exceeded (426 / 429),
or any network error occurs — callers never need to catch exceptions.

Free-tier constraints
---------------------
• 100 requests / day
• Articles up to 1 month old
• English headlines only (enforced here)

Capabilities
------------
fetch_company_news(company, page_size)
    Latest news articles mentioning the named company.
fetch_macro_news(topics, page_size)
    Latest macro / policy headlines built from FRED topic labels.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from ...schemas import RetrievedEvidence

logger = logging.getLogger(__name__)

_NEWS_BASE = "https://newsapi.org/v2/everything"

# ── Topic → human search query ────────────────────────────────────────────────
# Translates internal FRED topic names to concise NewsAPI search terms.
# NewsAPI supports AND / OR / NOT within a quoted query.

_TOPIC_QUERIES: dict = {
    "rates_fed":         "Federal Reserve OR interest rates OR FOMC OR rate cut OR rate hike",
    "yields":            "Treasury yields OR yield curve OR 10-year Treasury OR bond yields",
    "inflation":         "inflation OR CPI OR PCE OR consumer prices OR core inflation",
    "recession":         "recession OR GDP growth OR economic slowdown OR unemployment rate",
    "market_conditions": "VIX OR credit spreads OR market volatility OR risk off OR junk bonds",
}

# Fallback query when no topics matched.
_GENERAL_MARKET_QUERY = "stock market OR Federal Reserve OR S&P 500 OR economy"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_api_key() -> str:
    return os.environ.get("NEWS_API_KEY", "").strip()


def _fetch_json(url: str, timeout: int = 8):
    """Fetch JSON from *url* via stdlib urllib.  Raises on any error."""
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_macro_query(topics: List[str]) -> str:
    """Build a NewsAPI query string from a list of FRED topic names."""
    parts = [_TOPIC_QUERIES[t] for t in topics if t in _TOPIC_QUERIES]
    if not parts:
        return _GENERAL_MARKET_QUERY
    # Combine with OR so any matching article is returned.
    return " OR ".join(f"({p})" for p in parts)


def _article_to_evidence(article: dict, relevance: float) -> RetrievedEvidence:
    """Convert a single NewsAPI article dict to a RetrievedEvidence object."""
    title       = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    url         = article.get("url", "")
    published   = (article.get("publishedAt") or "")[:10]   # keep YYYY-MM-DD
    source_name = article.get("source", {}).get("name", "NewsAPI")

    # Combine description and URL into the summary field
    summary = description
    if url:
        summary = f"{description}  [Source: {url}]" if description else f"[Source: {url}]"

    return RetrievedEvidence(
        title=title or "(untitled)",
        source=f"NewsAPI / {source_name}",
        summary=summary or title,
        timestamp=published,
        relevance_score=relevance,
    )


def _request_news(query: str, page_size: int) -> List[dict]:
    """Call NewsAPI and return the raw articles list.  Returns [] on any error."""
    api_key = _get_api_key()
    if not api_key:
        print("[DIAG] NewsAPI: NEWS_API_KEY not set — skipping news fetch")
        return []

    params = urlencode({
        "q":        query,
        "apiKey":   api_key,
        "sortBy":   "publishedAt",
        "pageSize": page_size,
        "language": "en",
    })
    url = f"{_NEWS_BASE}?{params}"

    # Mask key in diagnostic — show only first 4 chars
    key_hint = (api_key[:4] + "...") if len(api_key) >= 4 else "***"
    safe_params = urlencode({
        "q":        query,
        "apiKey":   key_hint,
        "sortBy":   "publishedAt",
        "pageSize": page_size,
        "language": "en",
    })
    print(f"[DIAG] NewsAPI REQUEST: {_NEWS_BASE}?{safe_params}")

    try:
        data = _fetch_json(url)
        status = data.get("status", "")
        if status != "ok":
            code = data.get("code", "")
            msg  = data.get("message", "")
            logger.warning("NewsAPI error status=%s code=%s: %s", status, code, msg)
            print(f"[DIAG] NewsAPI: non-ok status={status!r} code={code!r} msg={msg!r}")
            return []
        articles = data.get("articles", [])
        # Filter out articles with empty/removed content
        return [a for a in articles if a.get("title") and "[Removed]" not in a.get("title", "")]
    except HTTPError as exc:
        logger.warning("NewsAPI HTTP %d: %s", exc.code, exc.reason)
        print(f"[DIAG] NewsAPI: HTTP {exc.code}: {exc.reason!r}")
    except URLError as exc:
        logger.warning("NewsAPI network error: %r", exc.reason)
        print(f"[DIAG] NewsAPI: network error: {exc.reason!r}")
    except Exception as exc:
        logger.warning("NewsAPI unexpected error: %r", exc)
        print(f"[DIAG] NewsAPI: unexpected error: {exc!r}")
    return []


# ── Public provider functions ─────────────────────────────────────────────────

def fetch_company_news(company: str, page_size: int = 3) -> List[RetrievedEvidence]:
    """Fetch the most recent news headlines about *company*.

    Parameters
    ----------
    company : str
        Company name or ticker (used as-is in the NewsAPI query).
    page_size : int
        Number of articles to request (max 5 on free tier).

    Returns
    -------
    List[RetrievedEvidence]
        Up to *page_size* evidence objects, newest first.
    """
    if not company or not company.strip():
        return []

    query   = f'"{company.strip()}"'
    articles = _request_news(query, page_size)

    evidence = [
        _article_to_evidence(a, relevance=0.88 - i * 0.02)
        for i, a in enumerate(articles[:page_size])
    ]
    print(f"[DIAG] NewsAPI: {len(evidence)} company article(s) for '{company}'")
    return evidence


def fetch_macro_news(topics: List[str], page_size: int = 3) -> List[RetrievedEvidence]:
    """Fetch recent macro / policy headlines based on FRED *topics*.

    Parameters
    ----------
    topics : list of str
        FRED topic names (from ``_detect_topics``), e.g. ``["yields", "inflation"]``.
        When empty, a general market query is used as a fallback.
    page_size : int
        Number of articles to request.

    Returns
    -------
    List[RetrievedEvidence]
        Up to *page_size* evidence objects, newest first.
    """
    query    = _build_macro_query(topics)
    articles = _request_news(query, page_size)

    evidence = [
        _article_to_evidence(a, relevance=0.82 - i * 0.02)
        for i, a in enumerate(articles[:page_size])
    ]
    print(f"[DIAG] NewsAPI: {len(evidence)} macro article(s) for topics={topics}")
    return evidence
