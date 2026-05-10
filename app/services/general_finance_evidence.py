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

  Interest rates / Fed policy  →  FEDFUNDS, DFEDTARU, DFEDTARL, DGS2, DGS10
  Treasury / bond yields       →  DGS10, DGS2, T10Y2Y
  Inflation                    →  CPIAUCSL, CPILFESL, PCEPILFE
  Recession / economy          →  T10Y2Y, UNRATE, A191RL1Q225SBEA, INDPRO
  Market conditions            →  VIXCLS, BAMLH0A0HYM2, BAMLC0A0CM

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
import re
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
    "PCEPILFE": (
        "Core PCE Price Index (Excl. Food & Energy)",
        "",
        "Core PCE is the Federal Reserve's preferred inflation gauge, stripping "
        "out volatile food and energy prices to reveal underlying price pressure. "
        "The Fed targets 2% core PCE; readings persistently above that delay rate cuts.",
    ),
    "A191RL1Q225SBEA": (
        "Real GDP Growth Rate (Quarterly, SAAR %)",
        "%",
        "Real GDP growth shows whether the economy is expanding or contracting on "
        "a seasonally adjusted annualised basis. Two consecutive negative quarters "
        "meet the informal recession definition.",
    ),
    "VIXCLS": (
        "CBOE Volatility Index (VIX)",
        "",
        "The VIX measures expected 30-day S&P 500 volatility implied by options prices. "
        "Readings above 20 signal elevated uncertainty; above 30 indicate fear-driven "
        "de-risking; spikes above 40 reflect crisis-level stress.",
    ),
    "BAMLH0A0HYM2": (
        "ICE BofA US High Yield Option-Adjusted Spread",
        " pp",
        "The high-yield OAS measures the extra yield investors demand over Treasuries "
        "to hold sub-investment-grade bonds. Widening spreads signal rising default risk "
        "and credit-market stress; tightening reflects improving risk appetite.",
    ),
    "BAMLC0A0CM": (
        "ICE BofA US Corporate Bond Option-Adjusted Spread",
        " pp",
        "The investment-grade corporate OAS tracks the risk premium over Treasuries "
        "for IG credit. Widening signals credit stress even before a default cycle; "
        "tightening reflects easy financial conditions and strong demand for credit.",
    ),
}


# ── Topic → [(series_id, relevance_score), …] ────────────────────────────────
# Relevance scores reflect how directly each series answers the topic.
# Series within a topic are listed highest-relevance first.

_TOPIC_SERIES: dict = {
    "rates_fed": [
        ("FEDFUNDS",  0.95),   # effective fed funds rate
        ("DFEDTARU",  0.88),   # target upper bound
        ("DFEDTARL",  0.85),   # target lower bound
        ("DGS2",      0.80),   # 2-yr Treasury tracks near-term policy expectations
        ("DGS10",     0.72),   # 10-yr for broader rate environment context
    ],
    "yields": [
        ("DGS10",  0.95),
        ("DGS2",   0.88),
        ("T10Y2Y", 0.80),
    ],
    "inflation": [
        ("CPIAUCSL",  0.95),   # headline CPI
        ("CPILFESL",  0.90),   # core CPI (excl. food & energy)
        ("PCEPILFE",  0.85),   # core PCE — the Fed's preferred gauge
    ],
    "recession": [
        ("T10Y2Y",           0.92),  # yield curve — leading recession signal
        ("UNRATE",           0.88),  # unemployment rate
        ("A191RL1Q225SBEA",  0.84),  # real GDP growth rate (quarterly SAAR %)
        ("INDPRO",           0.78),  # industrial production
    ],
    "market_conditions": [
        ("VIXCLS",        0.92),  # CBOE VIX — fear/volatility gauge
        ("BAMLH0A0HYM2",  0.88),  # high-yield credit spread
        ("BAMLC0A0CM",    0.82),  # investment-grade credit spread
    ],
}


# ── Topic keyword patterns ────────────────────────────────────────────────────
# All keywords are lowercase; detection runs against normalize_macro_query()
# output, not the raw question.

_TOPIC_KEYWORDS: dict = {
    "rates_fed": [
        "interest rate", "fed rate", "fed funds", "federal reserve", "fomc",
        "rate cut", "cut rate",           # covers both "rate cut" and "cut rates"
        "rate hike", "rate increase", "rate decrease",
        "monetary policy", "hiking", "cutting rate", "powell",
        " fed ",                           # "the Fed", "when the Fed"
        # colloquial Fed-action phrases (see _NORMALIZATIONS for canonical forms)
        "fed cut", "fed hike", "fed cuts", "fed hikes",
        "fed pivot", "fed pause", "fed hold",
        "rate cuts", "rate reduction",
    ],
    "yields": [
        # canonical forms produced by normalize_macro_query
        "treasury yield", "treasury yields",
        "bond yield", "bond yields",
        "10-year yield", "10 year yield",
        "2-year yield", "2 year yield",
        # raw terms that survive normalization unchanged
        "yield curve", "t10y2y", "sovereign",
        "bond market", "government bond",
        "long-term rate", "long term rate",
    ],
    "inflation": [
        "inflation", "cpi", "consumer price", "deflation", "disinflation",
        "price level", "purchasing power", "pce", "core inflation", "core pce",
        "price increase", "price rise",
        # additional colloquials
        "inflation rising", "inflation falling", "inflation higher", "inflation lower",
        "sticky inflation", "price pressures", "price pressure", "inflationary",
        "pce inflation", "pce price",
    ],
    "recession": [
        "recession", "unemployment", "gdp", "economic growth", "contraction",
        "industrial production", "jobs report", "labor market",
        "slowdown", "downturn", "economy",
        # additional recession-risk phrases
        "recession risk", "growth risk", "hard landing", "soft landing",
        "economic slowdown", "economic contraction", "negative growth",
        # yield-curve inversion phrasing (supplement to yields topic)
        "inverted yield", "yield curve invert", "curve inversion",
        "inversion", "2s10s",
    ],
    "market_conditions": [
        "vix", "market volatility", "volatility spike", "volatility index",
        "credit spread", "credit spreads", "high yield spread",
        "junk bond spread", "junk bond", "high yield",
        "risk off", "risk-off", "risk appetite",
        "spreads widening", "spread widening", "spreads widen",
        "financial conditions", "financial stress", "market stress",
        "credit stress", "flight to quality", "flight to safety",
    ],
}

# ── Phrase normalization table ────────────────────────────────────────────────
# Applied left-to-right after lowercasing + punctuation removal.
# Order matters: more specific phrases appear before their substrings.
# Each entry is (pattern_to_replace, replacement).

_NORMALIZATIONS: list = [
    # ── Treasury / yields conflations ────────────────────────────────────────
    ("treasury rates yields",       "treasury yields"),
    ("treasury rate yields",        "treasury yields"),
    ("treasury rates yield",        "treasury yields"),
    ("treasury bond rates",         "treasury yields"),
    ("treasury bond yield",         "treasury yields"),
    ("government bond rates",       "treasury yields"),
    ("government bond yields",      "treasury yields"),
    ("bond rates",                  "bond yields"),
    ("bond market rates",           "bond yields"),
    # ── Spelled-out maturities ────────────────────────────────────────────────
    # Hyphen variants ("10-year treasury") are intentionally omitted: the
    # treasury co-occurrence rule in _detect_topics handles them without
    # cascading replacements.
    ("ten year treasury",           "10-year treasury yield"),
    ("ten-year treasury",           "10-year treasury yield"),
    ("10 year treasury",            "10-year treasury yield"),
    ("two year treasury",           "2-year treasury yield"),
    ("two-year treasury",           "2-year treasury yield"),
    ("2 year treasury",             "2-year treasury yield"),
    # ── Long / short term ────────────────────────────────────────────────────
    ("long term rates",             "long-term rate"),
    ("long-term rates",             "long-term rate"),
    ("short term rates",            "2-year treasury yield"),
    ("short-term rates",            "2-year treasury yield"),
    # ── Colloquial "rates going up / ripping" ────────────────────────────────
    ("rates ripping",               "yields rising"),
    ("rates going up",              "yields rising"),
    ("rates moving higher",         "yields rising"),
    ("rates rising",                "yields rising"),
    # ── Colloquial Fed-action phrases → canonical keyword forms ───────────────
    # More specific phrases must come before shorter substrings (e.g.
    # "fed cuts rates" before "fed cuts") so they match first.
    ("fed cuts rates",              "rate cut"),
    ("fed hikes rates",             "rate hike"),
    ("fed cutting rates",           "rate cut"),
    ("fed hiking rates",            "rate hike"),
    ("fed is cutting",              "rate cut"),
    ("fed is hiking",               "rate hike"),
    ("fed are cutting",             "rate cut"),
    ("fed are hiking",              "rate hike"),
    # ── Yield-curve inversion colloquials → canonical "yield curve" ───────────
    ("inverted yield curve",        "yield curve"),
    ("yield curve inverted",        "yield curve"),
    ("yield curve inversion",       "yield curve"),
    ("curve is inverted",           "yield curve"),
    # ── Credit / volatility colloquials ──────────────────────────────────────
    ("credit spreads are widening", "credit spreads widening"),
    ("spreads are widening",        "credit spreads widening"),
    ("spreads blowing out",         "credit spreads widening"),
]


def normalize_macro_query(question: str) -> str:
    """Return a normalised version of *question* for FRED topic detection.

    Steps
    -----
    1. Lowercase.
    2. Remove punctuation (everything except letters, digits, spaces, hyphens).
    3. Collapse multiple whitespace characters to a single space and strip.
    4. Apply the phrase-substitution table ``_NORMALIZATIONS`` left-to-right.

    The result is only used for keyword matching — the original question is
    preserved for the LLM prompt.

    Parameters
    ----------
    question : str
        Raw user question.

    Returns
    -------
    str
        Normalised string suitable for substring keyword matching.
    """
    q = question.lower()
    # Keep letters, digits, spaces, and hyphens; strip everything else
    q = re.sub(r"[^\w\s-]", " ", q)
    # Collapse runs of whitespace (including newlines, tabs)
    q = re.sub(r"\s+", " ", q).strip()
    for src, dst in _NORMALIZATIONS:
        q = q.replace(src, dst)
    return q


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

    # Build the request params in the order the FRED API docs specify.
    # sort_order=desc returns the most recent observations first so we can
    # take observations[0] as the latest value without slicing.
    req_params: dict = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(limit),
    }
    url = f"{_FRED_BASE}/series/observations?{urlencode(req_params)}"

    # ── Diagnostic: log the request with a masked API key ─────────────────────
    # Show only the first 4 characters so the real key never appears in logs.
    key_hint = (api_key[:4] + "...") if len(api_key) >= 4 else "***"
    safe_params = urlencode({
        "series_id": series_id,
        "api_key": key_hint,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(limit),
    })
    print(
        f"[DIAG] FRED REQUEST — {_FRED_BASE}/series/observations?{safe_params} "
        f"(key_len={len(api_key)})"
    )

    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        observations = data.get("observations", [])
        return [
            o for o in observations
            if o.get("value") not in (".", None, "")
        ]
    except HTTPError as exc:
        # Read the error body — FRED includes a human-readable reason for 400s
        # (e.g. "Bad Request. Variable api_key is not correctly formatted.").
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "FRED HTTP %d for %s: %s | body: %s",
            exc.code, series_id, exc.reason, error_body[:500],
        )
        print(
            f"[DIAG] FRED HTTP {exc.code} for {series_id}: {exc.reason!r} "
            f"| body: {error_body[:500]!r}"
        )
        return []
    except URLError as exc:
        logger.warning("FRED network error for %s: %r", series_id, exc.reason)
        print(f"[DIAG] FRED NETWORK ERROR for {series_id}: {exc.reason!r}")
        return []
    except Exception as exc:
        logger.warning("FRED unexpected error for %s: %r", series_id, exc)
        print(f"[DIAG] FRED UNEXPECTED ERROR for {series_id}: {exc!r}")
        return []


# ── Topic detection ───────────────────────────────────────────────────────────

def _detect_topics(question: str) -> List[str]:
    """Return FRED topic names whose keywords appear in the question.

    The question is first passed through ``normalize_macro_query`` so that
    messy phrasings like "treasury rates yields" or "ten year treasury" still
    match the canonical keyword list.

    A treasury co-occurrence rule supplements keyword matching: if the
    normalised query contains "treasury" together with any of "rate", "yield",
    "bond", or "10-year", the ``yields`` topic is always included.

    Parameters
    ----------
    question : str
        The user's question (raw, any casing / punctuation).

    Returns
    -------
    List[str]
        Matching topic names (subset of ``_TOPIC_SERIES`` keys), deduplicated,
        preserving insertion order.  Returns ``[]`` when no topic is detected.
    """
    q = normalize_macro_query(question)

    topics: List[str] = [
        topic
        for topic, keywords in _TOPIC_KEYWORDS.items()
        if any(kw in q for kw in keywords)
    ]

    # ── Treasury co-occurrence rule ───────────────────────────────────────────
    # If the question mentions "treasury" alongside any yield/rate/bond signal,
    # force the yields topic regardless of exact phrase matching.
    _TREASURY_COMPANIONS = ("rate", "yield", "bond", "10-year", "2-year")
    if (
        "treasury" in q
        and any(c in q for c in _TREASURY_COMPANIONS)
        and "yields" not in topics
    ):
        topics.append("yields")

    # ── Inversion / 2s10s rule ────────────────────────────────────────────────
    # "inverted yield curve" and related phrases should pull both the yields
    # topic (for current rate data) and the recession topic (for context on
    # what an inversion historically signals).  After normalisation "yield curve"
    # covers the yields side; this rule ensures recession is also included.
    _INVERSION_SIGNALS = ("yield curve", "inverted yield", "2s10s", "curve inversion")
    if (
        any(sig in q for sig in _INVERSION_SIGNALS)
        and "recession" not in topics
    ):
        topics.append("recession")

    return topics


# ── T10Y2Y evidence builder ───────────────────────────────────────────────────

def _build_t10y2y_evidence(value_str: str, date_str: str) -> tuple:
    """Build an explicit (title, summary) pair for the T10Y2Y spread.

    The generic title/summary template does not encode whether the yield
    curve is inverted or positively sloped, which causes LLMs to guess
    (and frequently guess wrong).  This builder parses the numeric value
    and stamps the correct slope direction directly into the evidence text.

    T10Y2Y is defined as 10-year Treasury yield MINUS 2-year Treasury yield:
      - Positive value → 10-year > 2-year → curve is positively sloped, NOT inverted.
      - Negative value → 2-year > 10-year → curve is INVERTED.
      - Zero             → flat curve.

    Parameters
    ----------
    value_str : str   FRED observation value (e.g. "0.49" or "-0.52").
    date_str  : str   Observation date (e.g. "2024-11-15").

    Returns
    -------
    tuple[str, str]   (title, summary) ready for RetrievedEvidence.
    """
    try:
        val = float(value_str)
    except (ValueError, TypeError):
        # Unparseable — fall back to neutral wording, don't crash.
        title = (
            f"10-Year Minus 2-Year Treasury Spread: {value_str} pp "
            f"(as of {date_str})"
        )
        summary = (
            f"The 2s10s spread (10-year minus 2-year Treasury yield) is "
            f"{value_str} pp as of {date_str}. "
            "The 2s10s spread measures the slope of the yield curve. "
            "A negative spread (inverted curve) has historically preceded "
            "U.S. recessions by 12–18 months."
        )
        return title, summary

    sign = "+" if val >= 0 else ""

    if val > 0:
        slope_label = "NOT inverted — positively sloped"
        direction = (
            f"The 10-year Treasury yield exceeds the 2-year Treasury yield "
            f"by {val:.2f} pp. The curve is positively sloped and is NOT inverted."
        )
        recession_note = (
            "Historically, the yield curve inverts (spread turns negative) "
            "12–18 months before a U.S. recession; the current positive spread "
            "does not signal imminent recession on this measure."
        )
    elif val < 0:
        slope_label = "INVERTED"
        direction = (
            f"The 2-year Treasury yield exceeds the 10-year Treasury yield "
            f"by {abs(val):.2f} pp. The curve is inverted."
        )
        recession_note = (
            "An inverted yield curve has historically preceded U.S. recessions "
            "by 12–18 months."
        )
    else:  # val == 0
        slope_label = "flat"
        direction = (
            "The 10-year and 2-year Treasury yields are equal — the curve is flat."
        )
        recession_note = (
            "A flat curve is transitional; inversion (negative spread) has "
            "historically preceded U.S. recessions by 12–18 months."
        )

    title = (
        f"10-Year Minus 2-Year Treasury Spread: {sign}{val:.2f} pp "
        f"— yield curve is {slope_label} (as of {date_str})"
    )
    summary = (
        f"The 2s10s spread (10-year minus 2-year Treasury yield) is "
        f"{sign}{val:.2f} pp as of {date_str}. "
        f"{direction} {recession_note}"
    )
    return title, summary


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
    5. Deduplicate, sort by relevance_score descending, return top 6.

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
    # ── DIAGNOSTIC HEADER ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[DIAG] EVIDENCE RETRIEVAL PIPELINE — START")
    print("=" * 60)

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        logger.debug("FRED_API_KEY not set — evidence retrieval skipped")
        print("[DIAG] FRED_API_KEY: NOT SET — retrieval skipped")
        print("=" * 60 + "\n")
        return []

    print(f"[DIAG] FRED_API_KEY: SET (len={len(api_key)})")

    # ── [1] NORMALIZED QUERY ──────────────────────────────────────────────────
    normalized = normalize_macro_query(question)
    print(f"[DIAG] 1. NORMALIZED QUERY:  {normalized!r}")

    # ── [2] DETECTED TOPICS ───────────────────────────────────────────────────
    topics = _detect_topics(question)
    print(f"[DIAG] 2. DETECTED TOPICS:   {topics}")

    if not topics:
        logger.debug("No FRED topics matched for question: %r", question)
        print("[DIAG]    → no topics matched — retrieval returns []")
        print("=" * 60 + "\n")
        return []

    # ── [3] MATCHED FRED SERIES IDS ───────────────────────────────────────────
    matched_series = [
        series_id
        for topic in topics
        for series_id, _ in _TOPIC_SERIES.get(topic, [])
    ]
    # Deduplicate while preserving order (mirrors the seen-set logic below)
    seen_preview: set = set()
    unique_series = []
    for sid in matched_series:
        if sid not in seen_preview:
            seen_preview.add(sid)
            unique_series.append(sid)
    print(f"[DIAG] 3. MATCHED FRED SERIES IDs: {unique_series}")

    evidence: List[RetrievedEvidence] = []
    seen: set = set()

    for topic in topics:
        for series_id, relevance in _TOPIC_SERIES.get(topic, []):
            if series_id in seen:
                continue
            seen.add(series_id)

            observations = fetch_fred_series(series_id, limit=3)

            # ── [4] RAW FRED OBSERVATIONS COUNT ──────────────────────────────
            print(
                f"[DIAG] 4. RAW FRED OBSERVATIONS — {series_id}: "
                f"{len(observations)} observation(s)"
            )

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

            # ── T10Y2Y special case: encode slope direction explicitly ─────────
            # The generic template does not state whether the curve is inverted
            # or positively sloped, so LLMs frequently misread the sign.
            # Build the title and summary from the numeric value directly.
            if series_id == "T10Y2Y":
                title, summary = _build_t10y2y_evidence(value, date_str)
            else:
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
    final = evidence[:6]   # cap at 6 — gives room for multi-topic coverage

    # ── [5] FINAL RETRIEVED EVIDENCE OBJECTS ──────────────────────────────────
    print(f"[DIAG] 5. FINAL RETRIEVED EVIDENCE OBJECTS: {len(final)} item(s)")
    for i, ev in enumerate(final, 1):
        print(f"[DIAG]    [{i}] {ev.title}  (relevance={ev.relevance_score:.2f})")

    print("=" * 60 + "\n")
    return final


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
