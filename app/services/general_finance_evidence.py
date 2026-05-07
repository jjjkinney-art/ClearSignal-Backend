"""
General finance evidence retrieval service.

Architecture
------------
retrieve_general_finance_evidence(question) is the single public entry
point consumed by run_general_finance_agent() and
run_general_fallback_agent().  It returns a ranked list of
RetrievedEvidence objects that are injected into the LLM prompt as a
"Current Context" section, grounding the answer in recent developments
rather than model memory alone.

FRED integration
----------------
When the environment variable FRED_API_KEY is set, this service fetches
live macro data from the St. Louis Fed FRED API and converts it to
RetrievedEvidence objects:

  Interest rates / Fed policy  →  FEDFUNDS, DFEDTARU, DFEDTARL
  Treasury / bond yields       →  DGS10, DGS2, T10Y2Y
  Inflation                    →  CPIAUCSL, CPILFESL
  Recession / economy          →  UNRATE, GDPC1, INDPRO

If FRED_API_KEY is absent, topics don't match, or any network/API error
occurs, retrieve_general_finance_evidence() returns [] so the prompt
falls back to conceptual reasoning — /api/ask never crashes.

Adding more providers
---------------------
1. Implement a fetch function analogous to fetch_fred_series().
2. Detect relevant topics / tickers from the question.
3. Convert raw results to RetrievedEvidence objects.
4. Merge with FRED results inside retrieve_general_finance_evidence().
5. No changes needed to agents.py or prompts.py.

Test helpers
------------
_mock_evidence_for_question() returns pre-written mock evidence for
the four documented spec test cases.  Used by tests only — never called
by production code.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from ..schemas import RetrievedEvidence

logger = logging.getLogger(__name__)


# ── FRED API base URL ─────────────────────────────────────────────────────────

_FRED_BASE = "https://api.stlouisfed.org/fred"


# ── Per-series metadata ───────────────────────────────────────────────────────
# Tuple layout: (display_title, unit_suffix, one-sentence description)
# unit_suffix is appended directly to the numeric value in titles/summaries.

_SERIES_META: dict = {
    "FEDFUNDS": (
        "Federal Funds Rate (Effective)",
        "%",
        "The federal funds rate is the overnight rate at which banks lend "
        "reserves to each other; it is the Fed's primary lever for controlling "
        "inflation and economic activity.",
    ),
    "DFEDTARU": (
        "Fed Funds Target Rate — Upper Bound",
        "%",
        "The upper bound of the FOMC's target corridor for the fed funds rate, "
        "set at each policy meeting.",
    ),
    "DFEDTARL": (
        "Fed Funds Target Rate — Lower Bound",
        "%",
        "The lower bound of the FOMC's target corridor for the fed funds rate; "
        "together with the upper bound it defines the policy range.",
    ),
    "DGS10": (
        "10-Year Treasury Constant Maturity Rate",
        "%",
        "The 10-year Treasury yield is the benchmark long-term rate investors "
        "use to price bonds, mortgages, and equity valuations — rising yields "
        "increase discount rates for future earnings.",
    ),
    "DGS2": (
        "2-Year Treasury Constant Maturity Rate",
        "%",
        "The 2-year yield closely tracks Fed policy expectations; when it rises "
        "sharply it signals markets are pricing in more rate hikes or fewer cuts.",
    ),
    "T10Y2Y": (
        "10-Year Minus 2-Year Treasury Spread",
        " pp",
        "The 2s10s spread measures the slope of the yield curve. When negative "
        "(inverted), it has historically preceded U.S. recessions by 12–18 months.",
    ),
    "CPIAUCSL": (
        "CPI — All Urban Consumers (Index Level)",
        "",
        "Headline CPI measures the average change in prices paid by consumers. "
        "The Fed targets roughly 2% annual CPI inflation; readings persistently "
        "above that extend the rate-hike cycle.",
    ),
    "CPILFESL": (
        "Core CPI — Excluding Food and Energy (Index Level)",
        "",
        "Core CPI strips out volatile food and energy prices to reveal underlying "
        "inflation. The Fed watches core CPI closely when calibrating rate policy.",
    ),
    "UNRATE": (
        "Civilian Unemployment Rate",
        "%",
        "The unemployment rate reflects labor-market slack. A tight labor market "
        "sustains consumer spending and gives the Fed room to keep rates higher.",
    ),
    "GDPC1": (
        "Real GDP (Billions, Chained 2017 Dollars)",
        " B",
        "Real GDP measures the size of the economy adjusted for inflation. "
        "Two consecutive quarters of declining real GDP is the informal "
        "definition of recession.",
    ),
    "INDPRO": (
        "Industrial Production Index",
        "",
        "The Industrial Production Index tracks output from manufacturing, "
        "mining, and utilities. Sustained declines signal contraction in "
        "goods-producing sectors ahead of broader slowdowns.",
    ),
}


# ── Topic → [(series_id, relevance_score), …] ────────────────────────────────
# Relevance scores reflect how directly each series answers the topic.
# Series within a topic are listed highest-relevance first.

_TOPIC_SERIES: dict = {
    "rates_fed": [
        ("FEDFUNDS", 0.95),
        ("DFEDTARU", 0.88),
        ("DFEDTARL", 0.85),
    ],
    "yields": [
        ("DGS10", 0.95),
        ("DGS2", 0.88),
        ("T10Y2Y", 0.80),
    ],
    "inflation": [
        ("CPIAUCSL", 0.95),
        ("CPILFESL", 0.90),
    ],
    "recession": [
        ("UNRATE", 0.90),
        ("GDPC1", 0.85),
        ("INDPRO", 0.80),
    ],
}


# ── Topic keyword patterns ────────────────────────────────────────────────────
# All keywords are lowercase; detection compares against question.lower().

_TOPIC_KEYWORDS: dict = {
    "rates_fed": [
        "interest rate", "fed rate", "fed funds", "federal reserve", "fomc",
        "rate cut", "cut rate",          # "rate cut" and "cut rates" both covered
        "rate hike", "rate increase", "rate decrease",
        "monetary policy", "hiking", "cutting rate", "powell",
        " fed ",                          # "the Fed", "when the Fed", "what Fed"
    ],
    "yields": [
        "yield", "treasury", "bond yield", "10-year", "2-year",
        "yield curve", "t10y2y", "sovereign", "bond market",
    ],
    "inflation": [
        "inflation", "cpi", "consumer price", "deflation", "disinflation",
        "price level", "purchasing power", "pce", "core inflation",
        "price increase", "price rise",
    ],
    "recession": [
        "recession", "unemployment", "gdp", "economic growth", "contraction",
        "industrial production", "jobs report", "labor market",
        "slowdown", "downturn", "economy",
    ],
}


# ── FRED HTTP client ──────────────────────────────────────────────────────────

def fetch_fred_series(series_id: str, limit: int = 5) -> List[dict]:
    """Fetch recent observations from FRED for a single series.

    Reads FRED_API_KEY from the environment each time it is called so that
    tests can control the key via ``monkeypatch.setenv`` without reloading
    the module.

    Parameters
    ----------
    series_id : str
        A valid FRED series identifier (e.g. ``"DGS10"``).
    limit : int
        Maximum number of observations to request (most recent first).

    Returns
    -------
    List[dict]
        A list of ``{"date": "YYYY-MM-DD", "value": "<str>"}`` dicts, sorted
        newest-first, with FRED's missing-value sentinel ``"."`` filtered out.
        Returns ``[]`` on any error — callers never need to catch exceptions.
    """
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return []

    params = urlencode({
        "series_id": series_id,
        "api_key": api_key,
        "sort_order": "desc",
        "limit": str(limit),
        "file_type": "json",
    })
    url = f"{_FRED_BASE}/series/observations?{params}"

    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        observations = data.get("observations", [])
        return [
            o for o in observations
            if o.get("value") not in (".", None, "")
        ]
    except HTTPError as exc:
        logger.warning("FRED HTTP error for %s: %d %s", series_id, exc.code, exc.reason)
        return []
    except URLError as exc:
        logger.warning("FRED network error for %s: %r", series_id, exc.reason)
        return []
    except Exception as exc:
        logger.warning("FRED unexpected error for %s: %r", series_id, exc)
        return []


# ── Topic detection ───────────────────────────────────────────────────────────

def _detect_topics(question: str) -> List[str]:
    """Return FRED topic names whose keywords appear in the question.

    Parameters
    ----------
    question : str
        The user's question (case-insensitive keyword matching).

    Returns
    -------
    List[str]
        Matching topic names (subset of ``_TOPIC_SERIES`` keys).
        Returns ``[]`` when no macro topic is detected.
    """
    q = question.lower()
    return [
        topic
        for topic, keywords in _TOPIC_KEYWORDS.items()
        if any(kw in q for kw in keywords)
    ]


# ── Public entry point ────────────────────────────────────────────────────────

def retrieve_general_finance_evidence(question: str) -> List[RetrievedEvidence]:
    """Retrieve grounding evidence for a general finance or fallback question.

    Workflow
    --------
    1. Return [] immediately if FRED_API_KEY is not set.
    2. Detect which macro topics the question touches.
    3. For each matching topic, fetch the associated FRED series.
    4. Convert each observation into a RetrievedEvidence object with a
       human-readable title and summary from ``_SERIES_META``.
    5. Deduplicate, sort by relevance_score descending, return top 5.

    On any error (missing key, network failure, bad JSON, …) the function
    returns ``[]`` so the prompt degrades gracefully to conceptual reasoning.

    Parameters
    ----------
    question : str
        The user's question exactly as received.

    Returns
    -------
    List[RetrievedEvidence]
        Ranked list, highest relevance first, ready for prompt injection.
    """
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        logger.debug("FRED_API_KEY not set — evidence retrieval skipped")
        return []

    topics = _detect_topics(question)
    if not topics:
        logger.debug("No FRED topics matched for question: %r", question)
        return []

    evidence: List[RetrievedEvidence] = []
    seen: set = set()

    for topic in topics:
        for series_id, relevance in _TOPIC_SERIES.get(topic, []):
            if series_id in seen:
                continue
            seen.add(series_id)

            observations = fetch_fred_series(series_id, limit=3)
            if not observations:
                continue

            latest = observations[0]
            date_str = latest.get("date", "unknown")
            value = latest.get("value", "N/A")

            meta = _SERIES_META.get(series_id)
            if meta:
                display_title, unit, description = meta
            else:
                display_title, unit, description = (
                    series_id, "", f"FRED series {series_id}."
                )

            title = f"{display_title}: {value}{unit} (as of {date_str})"
            summary = (
                f"The most recent reading for {display_title} is "
                f"{value}{unit} (as of {date_str}). {description}"
            )

            evidence.append(
                RetrievedEvidence(
                    title=title,
                    source="FRED (Federal Reserve Bank of St. Louis)",
                    summary=summary,
                    timestamp=date_str,
                    relevance_score=relevance,
                )
            )

    evidence.sort(key=lambda e: e.relevance_score, reverse=True)
    return evidence[:5]


# ── Test / development helpers ────────────────────────────────────────────────

def _mock_evidence_for_question(question: str) -> List[RetrievedEvidence]:
    """Return pre-written mock evidence for the four documented test cases.

    NOT called by production code.  Used exclusively by tests to verify
    that the evidence injection pipeline (retrieval → prompt injection →
    LLM call) works end-to-end with structurally correct evidence objects.

    Coverage
    --------
    - "Why are Treasury yields rising?"
    - "Why did tech stocks sell off today?"
    - "How does CPI affect rate expectations?"
    - "Why is Nvidia moving after earnings?"

    Each case returns 2 structurally correct RetrievedEvidence objects,
    ranked by relevance_score descending.
    """
    q = question.lower()

    # ── Treasury yields rising ────────────────────────────────────────────────
    if ("treasury" in q or "yield" in q) and (
        "rising" in q or "rise" in q or "why" in q or "higher" in q
    ):
        return [
            RetrievedEvidence(
                title="10-Year Treasury Yield Climbs to 4.8% on Strong Jobs Data",
                source="Reuters [mock]",
                summary=(
                    "The 10-year yield rose 15bps this week after non-farm payrolls beat "
                    "estimates by 80k jobs, reducing market expectations for near-term Fed "
                    "rate cuts from four cuts to two in 2024."
                ),
                timestamp="2024-01-15",
                relevance_score=0.95,
            ),
            RetrievedEvidence(
                title="Fed Minutes: Most Members Want Greater Confidence on Inflation",
                source="Federal Reserve [mock]",
                summary=(
                    "FOMC minutes showed members want more evidence that inflation is "
                    "sustainably moving toward 2% before cutting rates, pushing 10-year "
                    "yields higher as markets repriced the rate path."
                ),
                timestamp="2024-01-10",
                relevance_score=0.90,
            ),
        ]

    # ── Tech stocks sell-off ──────────────────────────────────────────────────
    if "tech" in q and (
        "sell" in q or "down" in q or "drop" in q or "today" in q or "off" in q
    ):
        return [
            RetrievedEvidence(
                title="Nasdaq Falls 2.4% as Rate Cut Hopes Fade After CPI Beat",
                source="Bloomberg [mock]",
                summary=(
                    "The Nasdaq Composite dropped 2.4% after December CPI came in at "
                    "3.4% vs 3.2% expected, pushing 10-year yields above 4.7% and "
                    "reducing 2024 rate cut expectations from six to four."
                ),
                timestamp="2024-01-11",
                relevance_score=0.93,
            ),
            RetrievedEvidence(
                title="High-Multiple Tech Names Underperform as Duration Risk Reprices",
                source="WSJ [mock]",
                summary=(
                    "Software and semiconductor names with P/E ratios above 40x fell "
                    "3–5%, while profitable mega-cap tech (Apple, Alphabet) held up "
                    "better — consistent with the duration sensitivity of high-growth "
                    "valuations to rising discount rates."
                ),
                timestamp="2024-01-11",
                relevance_score=0.87,
            ),
        ]

    # ── CPI and rate expectations ─────────────────────────────────────────────
    if "cpi" in q or (
        "inflation" in q and ("rate" in q or "expect" in q or "cut" in q)
    ):
        return [
            RetrievedEvidence(
                title="CPI Rises 3.4% YoY in December, Core Holds at 3.9%",
                source="Bureau of Labor Statistics [mock]",
                summary=(
                    "Headline CPI came in at 3.4% year-over-year vs 3.2% expected. "
                    "Core CPI (ex-food and energy) remained at 3.9%, suggesting services "
                    "inflation is proving stickier than the Fed's 2% target requires."
                ),
                timestamp="2024-01-11",
                relevance_score=0.97,
            ),
            RetrievedEvidence(
                title="Fed Funds Futures Reprice: March Cut Odds Fall from 73% to 48%",
                source="CME FedWatch [mock]",
                summary=(
                    "Following the hot CPI print, traders reduced bets on a March rate "
                    "cut from 73% to 48% probability. The implied number of 2024 cuts "
                    "fell from six to roughly four, lifting Treasury yields across the curve."
                ),
                timestamp="2024-01-11",
                relevance_score=0.94,
            ),
        ]

    # ── Nvidia post-earnings ──────────────────────────────────────────────────
    if "nvidia" in q or "nvda" in q:
        return [
            RetrievedEvidence(
                title="Nvidia Q4 Revenue $22.1B, Beats $20.4B Estimate by 8%; Guides Q1 to $24B",
                source="Nvidia Investor Relations [mock]",
                summary=(
                    "Nvidia reported Q4 FY2024 revenue of $22.1B, up 265% year-over-year. "
                    "Data center revenue of $18.4B was up 409% YoY, driven by hyperscaler "
                    "AI infrastructure buildout. Q1 FY2025 guidance of $24B beat the $21.9B "
                    "consensus by 10%."
                ),
                timestamp="2024-02-21",
                relevance_score=0.98,
            ),
            RetrievedEvidence(
                title="NVDA Surges 16%, Adds $277B Market Cap in Single Session",
                source="Bloomberg [mock]",
                summary=(
                    "Nvidia shares rose 16.4% on earnings day, adding the largest single-day "
                    "market cap gain in stock market history. The move reflected both the "
                    "beat-and-raise quarter and management commentary that AI demand shows "
                    "no sign of slowing across cloud providers and enterprises."
                ),
                timestamp="2024-02-22",
                relevance_score=0.95,
            ),
        ]

    return []
