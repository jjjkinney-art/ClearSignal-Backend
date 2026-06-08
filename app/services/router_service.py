"""
Routing service for natural language questions.

This module contains logic for classifying user questions and
invoking the appropriate specialist agents. The classification is
currently rule‑based (keyword spotting) for simplicity but can be
replaced with machine learning or LLM‑based routing in the future.
"""

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Dict, List, Any, Optional

# Import schema types explicitly so that type hints in this module are resolvable
from ..schemas import (
    QuestionRequest,
    AgentAnswerResponse,
    GroundingContext,
    EquityAnalysis,
    MacroAnalysis,
    OpportunityAnalysis,
    ResearchAnalysis,
    EducationAnalysis,
    AccountingAnalysis,
    SynthesisOutput,
    CompanyContext,
)
from ..agents import (
    run_equity_agent,
    run_macro_agent,
    run_opportunity_agent,
    run_research_agent,
    run_education_agent,
    run_accounting_agent,
    run_synthesizer_agent,
    run_general_finance_agent,
    run_general_fallback_agent,
)
from .context_service import enrich_grounding_context  # import context enrichment
# Import evidence selection and building functions to enrich the grounding
# context with real data.  These are used to gather financial metrics,
# recent filings and news before routing the question.  Keeping the
# evidence layer here mirrors the logic used in the analysis service
# and ensures that both /ask and /analyze endpoints operate on
# a provider‑backed GroundingContext.
from .evidence_service import select_evidence_sources, build_evidence
from .general_finance_evidence import _detect_topics, normalize_macro_query as _normalize_macro_query, retrieve_general_finance_evidence
from ..agents import _YIELD_FALLBACK_ANSWER, _GENERIC_EVIDENCE_FALLBACK

# ── Company detection + investment pipeline imports ───────────────────────────
from .company_detection import detect_company, resolve_entity, MINIMUM_ROUTE_CONFIDENCE
from .providers.fmp_provider import fetch_valuation_ratios, fetch_analyst_estimates
from .company_knowledge import get_profile_for_company
from .evidence_partitioner import partition_evidence
from .providers import retrieve_market_evidence
from .providers import fmp_provider as _fmp_provider
from .providers import sec_provider as _sec_provider
from .providers import news_provider as _news_provider
from ..investment_agents import (
    run_valuation_agent,
    run_investment_macro_agent,
    run_macro_agent,   # legacy path alias (router line ~1525)
    run_risk_agent,
    run_market_agent,
    run_quality_agent,
)
from .thesis_synthesizer import synthesize_thesis
from .watchlist_service import watchlist_service

# Set up a module-level logger for structured logging.  This logger will
# emit JSON-formatted messages about routing decisions.  The FastAPI
# application or calling code can configure logging handlers as needed.
logger = logging.getLogger(__name__)


# Define simple keyword patterns for routing.  Each key corresponds to an
# agent identifier and maps to a list of keywords.  If a keyword is found
# in the question, that agent will be considered relevant.
# Routing keyword patterns for classifying questions.  Each key
# corresponds to an agent identifier and maps to a list of keywords or
# phrases (case‑insensitive) that, when present in the question, suggest
# the agent is relevant.  These lists include synonyms and related
# terms to improve coverage and reduce misclassification.
ROUTING_KEYWORDS: Dict[str, List[str]] = {
    "macro": [
        "macro",
        "interest rate",
        "interest rates",
        "inflation",
        "economic",
        "economy",
        "geopolitical",
        "macro environment",
        "macroeconomic",
        "fed",
        "monetary policy",
        "recession",
    ],
    "opportunity": [
        "opportunity",
        "opportunities",
        "emerging",
        "theme",
        "themes",
        "ideas",
        "asymmetric",
        "catalyst",
        "catalysts",
        "trend",
        "trends",
        "disruption",
    ],
    "research": [
        "research",
        "report",
        "reports",
        "filing",
        "filings",
        "transcript",
        "transcripts",
        "study",
        "studies",
        "analysis",
        "analyst note",
        "earnings call",
        "10‑k",
        "10-k",
    ],
    "education": [
        "explain",
        "simple",
        "understand",
        "education",
        "teach",
        "layman",
        "layman’s terms",
        "plain language",
        "accessible",
    ],
    "accounting": [
        "accounting",
        "financial statement",
        "financial statements",
        "balance sheet",
        "income statement",
        "cash flow",
        "cashflow",
        "anomaly",
        "operations",
        "operational",
        "expenses",
        "revenue recognition",
        "quarterly results",
    ],
    # Equity is used as default catch‑all.  Include common investment
    # analysis terms beyond bull/bear to capture general equity
    # questions.
    "equity": [
        "business",
        "model",
        "revenue",
        "bull",
        "bear",
        "risks",
        "risk",
        "catalysts",
        "valuation",
        "fundamentals",
        "thesis",
        "investment thesis",
        "competitive advantage",
    ],
}


def classify_question(question: str) -> Dict[str, Any]:
    """Classify a question and return structured routing metadata.

    This rule‑based classifier searches for keywords in the question
    text and constructs a routing decision containing the following
    keys:

      * ``selected_agents``: a list of agent identifiers that should
        run, ordered by priority of the keyword mapping.  If no
        keywords match, equity is selected by default.
      * ``skipped_agents``: a list of agents that were not selected.
      * ``reasons``: a mapping from agent identifiers to the reason
        they were selected or skipped (e.g. which keyword matched or
        that no keywords were found).
      * ``confidence``: a heuristic confidence score between 0 and 1
        representing how many agents were selected relative to the
        total possible.  This is a simple measure of how clear the
        routing decision is (more matches yield higher confidence).

    The classifier performs a case‑insensitive search across all
    defined keywords and aggregates matches for each agent.  Duplicate
    selections are removed while preserving order.  Reasons are
    recorded for both selected and skipped agents for transparency.
    """
    text = question.lower() if question else ""
    # Collect all matched keywords per agent for richer reasoning
    matched_keywords: Dict[str, List[str]] = {}
    for agent, keywords in ROUTING_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched_keywords.setdefault(agent, []).append(kw)
    # Determine selection order by appearance order of agents in ROUTING_KEYWORDS
    ordered: List[str] = [a for a in ROUTING_KEYWORDS.keys() if a in matched_keywords]
    # If nothing matched, default to equity
    if not ordered:
        ordered = ["equity"]
    # Compute skipped agents
    skipped = [a for a in ROUTING_KEYWORDS.keys() if a not in ordered]
    # Build reasons with lists of matched keywords or default rationale
    reasons: Dict[str, str] = {}
    for agent in ordered:
        if agent in matched_keywords:
            kws = matched_keywords[agent]
            # Show up to three keywords in the reason for brevity
            display = ", ".join(kws[:3])
            if len(kws) > 3:
                display += ", ..."
            reasons[agent] = f"matched keywords: {display}"
        else:
            reasons[agent] = "no keywords matched; defaulting to equity"
    for agent in skipped:
        reasons[agent] = "no relevant keywords"
    # Compute a simple confidence score.  Instead of using a fixed
    # denominator, scale the confidence by the proportion of matched
    # keywords relative to the total number of words in the question.
    total_matches = sum(len(v) for v in matched_keywords.values())
    # Tokenize the question into words; fall back to 1 to avoid division by zero.
    words = re.findall(r"\b\w+\b", text)
    word_count = len(words) if words else 1
    # Confidence is the fraction of matched keyword occurrences to word count,
    # capped at 1.0.  This heuristic yields higher confidence for
    # densely keyworded questions and lower confidence for sparse ones.
    confidence = min(1.0, total_matches / word_count) if total_matches else 0.0
    return {
        "selected_agents": ordered,
        "skipped_agents": skipped,
        "reasons": reasons,
        "confidence": confidence,
    }


# ── Evidence-aware answer-quality guard ──────────────────────────────────────
# When the LLM answer already references real retrieved evidence, we must NOT
# replace it with a static fallback — that would discard live FRED data.
# This frozenset covers all the terms that can only appear in an answer when
# actual evidence was used.  It is intentionally broader than the per-agent
# _EVIDENCE_TERMS so that surface variants ("treasury yields" vs "treasury
# yield") are both caught.
_ROUTER_EVIDENCE_TERMS: frozenset = frozenset([
    # Treasury / yield curve
    "10-year treasury", "2-year treasury", "treasury yield", "treasury yields",
    "yield curve", "2s10s", "t10y2y", "dgs10", "dgs2",
    "constant maturity",
    # Fed / monetary policy
    "fed funds", "federal funds", "fedfunds", "fomc",
    # Inflation
    "cpi", "consumer price", "pce",
    # Labour / real economy
    "unemployment", "unrate", "nonfarm payroll",
    "gdp", "gdpc1", "industrial production", "indpro",
])


# ── Topic-specific fallback answers ──────────────────────────────────────────
# Each entry: (keyword_list, answer, bullets, caveats)
# Checked in order; first match wins.  Keywords are matched against the
# lowercased question using simple substring search.
_TOPIC_FALLBACKS = [
    # ── Bond yields ───────────────────────────────────────────────────────────
    (
        ["bond yield", "bond yields", "treasury yield", "treasury yields", "yield curve"],
        (
            "Bond yields affect the stock market because they change the return investors "
            "can earn from safer assets. When yields rise, stocks often face pressure "
            "because bonds become more attractive and future corporate profits are discounted "
            "at a higher rate."
        ),
        [
            "Higher yields reduce stock valuations, especially for growth stocks — their "
            "value is tied to earnings years away, and a higher discount rate shrinks that "
            "present value faster than it shrinks the value of a company earning profits today.",
            "Rising yields can pull money away from equities into bonds, as investors seek "
            "a better risk-adjusted return from a lower-risk asset.",
            "Falling yields can support stocks if they reflect lower inflation — but falling "
            "yields driven by recession fears are a different story and can still hurt stocks.",
        ],
        [
            "The reason behind a yield move matters as much as its direction — falling yields "
            "from a slowing economy are not the same signal as falling yields from easing "
            "inflation.",
            "Watch the 10-year Treasury yield and the yield curve spread (10-year minus "
            "2-year) — an inversion has historically preceded recessions.",
        ],
    ),
    # ── Interest rates ────────────────────────────────────────────────────────
    (
        ["interest rate", "interest rates", "rate hike", "rate cut", "rate rise",
         "rates rise", "rates fall", "raise rates", "cut rates"],
        (
            "Interest rates affect the economy through borrowing costs — higher rates make "
            "loans more expensive for businesses and consumers, which slows spending and "
            "investment. For stocks, rising rates tend to pressure valuations because future "
            "earnings are worth less when discounted at a higher rate."
        ),
        [
            "The discount rate effect: when rates rise, the present value of future cash "
            "flows falls. Growth stocks — which derive most of their value from distant "
            "future earnings — are hit harder than value stocks earning profits today.",
            "Higher rates also raise borrowing costs directly: companies with floating-rate "
            "debt see interest expenses rise, which compresses margins and free cash flow.",
            "Rate cuts tend to work in reverse — cheaper borrowing stimulates spending, "
            "and lower discount rates push up the present value of future earnings, which "
            "supports stock valuations.",
        ],
        [
            "The size and speed of rate changes matter as much as their direction — a slow "
            "rise from low levels is very different from a rapid rise from an already "
            "elevated base.",
            "Watch the Fed funds rate, the 10-year Treasury yield, and corporate credit "
            "spreads — together they tell you how tight financial conditions actually are "
            "for businesses.",
        ],
    ),
    # ── Fed meetings ─────────────────────────────────────────────────────────
    (
        ["fed meet", "fomc meet", "federal reserve meet", "fed meetings", "fomc meetings",
         "how often does the fed", "when does the fed", "fed schedule"],
        (
            "The Federal Reserve's FOMC meets eight times per year on a fixed schedule — "
            "roughly every six to eight weeks. Each meeting ends with a rate decision and "
            "a policy statement; every other meeting also includes updated economic "
            "projections and a press conference."
        ),
        [
            "Each meeting produces a rate decision (raise, cut, or hold) and a statement "
            "explaining the reasoning. The chair's press conference often moves markets "
            "more than the rate decision itself — investors parse every word for clues "
            "about future moves.",
            "Markets price rate expectations in advance using the CME FedWatch tool, which "
            "shows the probability of a rate change implied by fed funds futures. By the "
            "time a decision is announced, it is usually already priced in.",
            "The four most watched meetings — March, June, September, December — include "
            "the 'dot plot', which shows where each FOMC member expects rates to go over "
            "the next few years. Shifts in the dot plot can reprice markets significantly.",
        ],
        [
            "Emergency unscheduled meetings can happen in a crisis — the Fed cut rates "
            "between scheduled meetings in March 2020 during the pandemic.",
            "Mark the FOMC calendar (published at federalreserve.gov) — the days around "
            "meetings are historically among the most volatile for equities and bonds.",
        ],
    ),
    # ── Market crashes ────────────────────────────────────────────────────────
    (
        ["market crash", "markets crash", "stock crash", "crash happen", "crash occur",
         "why do markets", "why do stocks crash", "market collapse"],
        (
            "Markets crash when widespread selling overwhelms buying — usually triggered "
            "by a shock that forces investors to reprice risk all at once. The move is "
            "self-reinforcing: falling prices trigger margin calls and stop-losses, which "
            "force more selling, which pushes prices down further."
        ),
        [
            "The trigger is a repricing of risk: investors realise their assumptions about "
            "earnings, growth, or stability were too optimistic. Once that confidence "
            "breaks, exits accelerate and liquidity dries up quickly.",
            "Leverage amplifies crashes — investors who borrowed to buy assets are forced "
            "to sell as collateral values fall, regardless of whether they think it is the "
            "right time to sell.",
            "Historical crashes (2000, 2008, 2020) all share three elements: excessive "
            "leverage that forces selling, a narrative shift that changes what assets are "
            "worth, and a liquidity crunch that amplifies both.",
        ],
        [
            "Not every large drawdown is a crash — a 10–20% correction is normal and "
            "happens most years. A crash implies a faster, more disorderly decline driven "
            "by forced selling and a broad loss of confidence.",
            "Recoveries typically come faster than investors expect — missing the 10 best "
            "days in the market in most 20-year periods cuts returns by more than half, "
            "which is why timing a crash is so difficult.",
        ],
    ),
    # ── Inflation ─────────────────────────────────────────────────────────────
    (
        ["inflation", "inflat", "cpi", "consumer price"],
        (
            "Inflation erodes the purchasing power of money over time — when prices rise, "
            "each dollar buys less. For investors, the key question is whether inflation is "
            "running above or below what was already priced into asset valuations."
        ),
        [
            "High inflation tends to hurt long-duration assets (growth stocks, long bonds) "
            "because it raises the discount rate used to value future cash flows — making "
            "distant earnings worth less in today's dollars.",
            "Companies with pricing power — the ability to raise prices without losing "
            "customers — hold up better in inflationary periods; those with fixed-price "
            "contracts or commodity cost exposure are more vulnerable.",
            "Central banks fight inflation by raising interest rates, which slows borrowing "
            "and spending. This is the core tension: fighting inflation often means "
            "accepting slower growth and lower asset prices in the short term.",
        ],
        [
            "Moderate inflation (around 2%) is actually the Fed's target and is generally "
            "healthy for stocks — it becomes destructive when it runs well above that level "
            "or becomes unpredictable.",
            "Watch the CPI and PCE reports (published monthly) and the Fed's commentary on "
            "inflation expectations — persistent above-target inflation is the scenario that "
            "most pressures both stocks and bonds simultaneously.",
        ],
    ),
    # ── Recession ─────────────────────────────────────────────────────────────
    (
        ["recession", "economic downturn", "economic contraction", "gdp shrink",
         "gdp decline", "gdp negative"],
        (
            "A recession is typically defined as two consecutive quarters of negative GDP "
            "growth, but the official call in the US comes from the National Bureau of "
            "Economic Research based on a broader set of indicators. Recessions mean "
            "falling output, rising unemployment, and tighter consumer and business spending."
        ),
        [
            "For stocks, recessions are usually accompanied by falling earnings — companies "
            "sell less and margins compress, so the market's forward earnings estimates drop "
            "alongside the economy, pulling valuations down.",
            "Not all sectors suffer equally: consumer staples, healthcare, and utilities "
            "tend to be more defensive; industrials, consumer discretionary, and financials "
            "are more cyclical and take harder hits.",
            "The stock market often bottoms before the recession officially ends — investors "
            "are pricing future recovery, not current conditions. Historically the S&P 500 "
            "has bottomed around the midpoint of recessions, not at the end.",
        ],
        [
            "Recessions vary widely in depth and length — a mild contraction of a few "
            "quarters is very different from the 2008–09 financial crisis, which involved "
            "a collapse of the credit system alongside the economic downturn.",
            "Watch the yield curve, unemployment claims, ISM manufacturing PMI, and "
            "consumer confidence — together they give the best early warning of whether a "
            "recession is approaching.",
        ],
    ),
]

# Phrases that signal a generic, template-generated answer — used by the quality guard.
# Checked as startswith matches on the lowercased answer and as substring matches
# within the first 160 characters (typically the first two sentences).
_GENERIC_ANSWER_PREFIXES = (
    "this is a macro",
    "this is a market",
    "this topic involves",
    "financial markets respond to",
    "this question asks about",
    "portfolio decisions depend on",
    "this is a broad question",
    "this question touches on",
    "the answer depends on context",
    "financial markets respond",
    "markets respond to a combination",
    "understanding the underlying mechanism",
    "understanding how these mechanisms",
)

# Substring fragments banned anywhere in the first 160 chars of the answer.
# Catches template-insertion patterns like "X is an important concept..."
# that may not appear at the very start.
_GENERIC_ANSWER_FRAGMENTS = (
    "this is a macro",
    "this is a market",
    "this topic involves",
    "financial markets respond",
    "this question asks",
    "is an important concept",
    "is a key concept",
    "helps investors understand",
    "understanding the mechanism",
    "market participants",
    "related indicators",
    "this factor",
    "any effect depends on",
    "the direction and magnitude",
)


def _is_generic_answer(text: str) -> bool:
    """Return True if the answer contains generic template-generated language.

    Two checks:
      1. Banned opener — the answer starts with a known deflection phrase.
      2. Banned fragment — a template-insertion pattern appears in the first
         160 characters (covering the opening 1–2 sentences).

    Either check firing means the LLM produced a category description or
    template sentence rather than a direct answer.
    """
    lower = text.strip().lower()
    if any(lower.startswith(prefix) for prefix in _GENERIC_ANSWER_PREFIXES):
        return True
    opening = lower[:160]
    return any(frag in opening for frag in _GENERIC_ANSWER_FRAGMENTS)


def _topic_aware_fallback(question: str) -> tuple:
    """Return (answer, bullets, caveats) for the best-matching topic.

    Checks the question against _TOPIC_FALLBACKS in order and returns the
    first match.  When no topic keyword matches, returns a fixed analytical
    response written in natural analyst language — no template string
    insertion, no concept extraction.
    """
    q = question.lower()
    for keywords, answer, bullets, caveats in _TOPIC_FALLBACKS:
        if any(kw in q for kw in keywords):
            return answer, bullets, caveats

    # No topic matched.
    # Return a genuinely useful general response written in natural language.
    # Nothing is inserted from the question — the text is fixed and reads
    # like an analyst explaining how financial markets work.
    answer = (
        "Most market outcomes trace back to three forces: where interest rates "
        "are heading, whether corporate earnings are growing or shrinking, and "
        "how much risk investors are willing to take on. When any of these shifts "
        "more than the market expected, asset prices reprice — sometimes sharply."
    )
    bullets = [
        "Prices reflect expectations, not current conditions — markets move when "
        "reality diverges from what was already priced in, not simply when "
        "conditions change.",
        "Leverage amplifies both directions: when prices fall, margin calls force "
        "selling regardless of fundamentals; when they rise, momentum attracts "
        "more capital and pushes them higher still.",
        "The macro backdrop reframes every signal — the same earnings miss reads "
        "very differently at 2% rates than at 5% rates, or when credit spreads "
        "are tight versus when they are widening.",
    ]
    caveats = [
        "A more specific question will get a more precise answer — the general "
        "framework applies broadly, but the details depend on the asset class, "
        "time horizon, and current market regime.",
        "Being right about the direction isn't enough: timing matters, and markets "
        "can stay mispriced longer than most investors expect.",
    ]
    return answer, bullets, caveats


def _build_answer_fallback(question: str, intent: str) -> str:
    """Return a topic-aware fallback answer string.

    Called when the LLM returns an empty, too-short, or generic answer.
    Uses topic pattern matching to return a specific, direct answer rather
    than a generic category description.  Always produces at least 2 full
    sentences that directly address what the user asked.
    """
    answer, _bullets, _caveats = _topic_aware_fallback(question)
    return answer


def _detect_intent(question: str) -> str:
    """Lightweight server-side intent detection.

    Used only when the frontend does not pass an explicit intent.
    Returns one of:
      market_question | investing_education | portfolio_question | general_fallback

    Detection order:
      1. Personal portfolio signals → portfolio_question
      2. Finance keyword gate — if no finance term is present → general_fallback
         (broad/interdisciplinary questions that do not belong in the finance pipeline)
      3. Education signals within finance context → investing_education
      4. Everything else that IS finance-related → market_question

    This ensures that clearly non-finance questions (e.g. "How does AI affect
    productivity?") are not forced into the finance agents, while finance
    questions that happen to use broad language still reach the right pipeline.
    """
    q = question.lower()

    # ── 1. Personal portfolio ─────────────────────────────────────────────────
    if any(k in q for k in ("my portfolio", "my holdings", "i own", "i hold", "i bought",
                             "should i rebalance", "diversif")):
        return "portfolio_question"

    # ── 2. Finance keyword gate ───────────────────────────────────────────────
    # If none of these core finance terms appear, the question is too broad or
    # off-topic for the specialist finance agents — route to general_fallback.
    _FINANCE_KEYWORDS = (
        "stock", "stocks", "market", "markets", "invest", "investing", "investment",
        "fund", "funds", "bond", "bonds", "equity", "equities", "rate", "rates",
        "inflation", "economic", "economy", "financial", "finance", "company",
        "revenue", "earnings", "dividend", "dividends", "crypto", "currency",
        "trade", "trading", "fiscal", "monetary", "bank", "banking", "fed",
        "federal reserve", "yield", "yields", "price", "valuation", "asset",
        "assets", "return", "returns", "portfolio", "sector", "index", "indices",
        "bull", "bear", "recession", "gdp", "employment", "interest", "shares",
        "share", "nasdaq", "s&p", "dow", "etf", "hedge", "short", "long",
        "options", "futures", "derivatives", "ipo", "dividend", "earnings per",
        "p/e", "pe ratio", "cash flow", "balance sheet", "income statement",
    )
    is_finance = any(k in q for k in _FINANCE_KEYWORDS)

    if not is_finance:
        return "general_fallback"

    # ── 3. Education signals within finance context ───────────────────────────
    if any(k in q for k in ("what is", "what are", "how does", "how do", "explain",
                             "define", "difference between", "mean by", "tell me what",
                             "like i'm new", "for beginners", "simple terms", "simply")):
        return "investing_education"

    # ── 4. Finance market question (default for finance-tagged questions) ─────
    return "market_question"


# ── Investment intent keywords ────────────────────────────────────────────────
# A question mentioning a company AND one of these terms should route to the
# full 5-agent investment pipeline rather than the general finance path.
_INVESTMENT_INTENT_KEYWORDS: frozenset = frozenset([
    "stock", "stocks", "share", "shares", "equity", "invest", "investment",
    "bull", "bear", "thesis", "valuation", "affect", "impact", "exposure",
    "attractive", "buy", "sell", "hold", "overweight", "underweight",
    "target price", "price target", "earnings", "revenue", "margin", "margins",
    "moat", "competitive", "risk", "risks", "outlook", "forecast",
    "interest rate", "rates", "inflation", "recession", "macro",
    "how would", "how will", "what happens", "what would",
    # Common investment-question words missing from the original list.
    # "Is Visa overvalued?" and "Is ASML undervalued?" were falling through
    # to general_finance because these synonyms of "valuation" were absent.
    "overvalued", "undervalued", "overpriced", "underpriced",
    # "Can Eli Lilly maintain GLP-1 growth?" — "growth" is the most common
    # investment metric and was absent from the gate.
    "growth", "grow",
    # Pharma / biotech investment language.
    "pipeline", "approval", "trial", "clinical",
    # Broader investment-question patterns.
    "worth", "performance", "position", "upside", "downside",
    "dividend", "yield", "multiple", "pe ratio", "p/e",
])


def _has_investment_intent(question: str) -> bool:
    """Return True if the question signals investment/company analysis intent.

    Checks for keywords that distinguish a company-specific investment question
    ("How would higher rates affect Apple stock?") from a generic macro question
    ("Why are Treasury yields rising?").
    """
    q = question.lower()
    return any(kw in q for kw in _INVESTMENT_INTENT_KEYWORDS)


# ── Question-intent classifier ────────────────────────────────────────────────

_VALUATION_STANCE_PATTERNS: tuple = (
    # Direct price-fairness questions
    "overpriced", "over priced", "overvalued", "over valued",
    "underpriced", "under priced", "undervalued", "under valued",
    "fairly valued", "fairly priced", "fair value", "fair price",
    "too expensive", "too cheap", "cheap stock", "expensive stock",
    "worth buying", "worth the price", "priced correctly",
    "at a premium", "at a discount",
    # Is it a buy/avoid at current price?
    "buy at current", "buy at this price", "buy here", "avoid at",
    "good price", "right price", "wrong price",
    # Multiple-anchored questions
    "p/e too high", "pe too high", "pe ratio too", "multiple too",
    "stretched valuation", "stretched multiple", "stretched multiple",
    "discount to", "premium to peers", "cheap relative",
    # Phase 3 additions: multiple-compression and valuation-justification phrasing
    # that previously fell through to investment_thesis.
    # "multiple compress" matches "multiple compress" directly.
    # "multiple to compress" matches "What would cause X's multiple to compress?" phrasing.
    "multiple compress", "multiple compression",
    "multiple to compress", "multiple de-rate", "multiple derate",
    "p/e compress", "p/e compression", "p/e to compress",
    "pe compress", "pe compression", "pe to compress",
    "justify valuation", "valuation justified",
    "justify its valuation", "justify the valuation",
    "justify a valuation", "valuation to compress",
    "valuation compress", "de-rate", "derate",
    "cause the multiple", "cause its multiple",
    # Phase 4 additions: premium-justification phrasing for peer-comparison
    # valuation questions (e.g. V-P2: "Is the premium structurally justified…
    # what metric would cause it to compress?")
    "premium structurally", "premium justified", "premium warranted",
    "premium sustainable", "justify the premium", "is the premium",
    "cause it to compress",
)

_MACRO_SENSITIVITY_PATTERNS: tuple = (
    "how would", "how will", "what happens if", "impact of",
    "effect of", "affect", "rate hike", "rate cut", "inflation",
    "recession", "yield curve", "fed", "interest rate",
)

# ── Sprint 1 P1: macro-cross-company intent ───────────────────────────────────
# Fires when a question combines a macro trigger (report, Fed, CPI, rates) with
# explicit company-specific framing ("but specifically [company]", "for Nvidia",
# "and how does that affect [ticker]"). This is MORE specific than macro_sensitivity
# because the user wants both the sector-level macro chain AND the named company's
# individual exposure.  It is checked BEFORE macro_sensitivity so it takes priority.
#
# The macro trigger set deliberately mirrors the economic-data terms added to
# _CONTEXT_WORDS in company_detection.py (FCX regression fix, 2026-06-08).
# These terms identify questions about macro events rather than companies, but
# here we detect them *alongside* company-specificity signals.
_MACRO_TRIGGER_TERMS: frozenset = frozenset({
    "jobs report", "job report", "nonfarm payroll", "payroll report",
    "cpi", "ppi", "inflation report", "inflation data",
    "fed decision", "fed rate", "fomc", "rate decision",
    "gdp report", "gdp data", "economic report", "economic data",
    "employment report", "unemployment report", "jobless claims",
    "rate hike", "rate cut", "interest rate decision",
})
# A question crosses into macro_cross_company when it also carries a company-
# specificity signal: "but specifically", "especially for", "particularly for",
# "and specifically", "and for", combined with stock/ticker/shares framing.
_MACRO_CROSS_COMPANY_SIGNALS: tuple = (
    "but specifically",
    "specifically for",
    "but especially",
    "especially for",
    "particularly for",
    "in particular for",
    "and specifically",
    "and for nvidia", "and for apple", "and for tesla", "and for meta",
    "and for microsoft", "and for amazon", "and for google",
    "and for alphabet",
    "impact on nvidia", "impact on apple", "impact on tesla",
    "impact on meta", "impact on microsoft", "impact on amazon",
    "for nvidia stock", "for apple stock", "for tesla stock",
    "for nvda", "for aapl", "for tsla", "for msft", "for amzn",
    "for googl", "for meta", "for goog",
    # Generic: "and how does that affect [company]"
    "how does that affect",
    "how would that affect",
    "what does that mean for",
    "what does this mean for",
)


def _is_macro_cross_company(question: str) -> bool:
    """Return True when the question mixes a macro trigger with company-specific framing.

    Uses two-gate detection:
      Gate 1 — at least one macro trigger term is present (jobs report, CPI, etc.)
      Gate 2 — at least one company-specificity signal is present
               ("but specifically Nvidia", "for NVDA stock", etc.)

    Checked BEFORE macro_sensitivity in _detect_question_intent so it takes
    priority for the cross-over pattern.

    Regression test:
      "How will the latest jobs report impact tech stocks generally but
       specifically Nvidia stock?" → True
      "How will the Fed decision affect bank stocks?" → False (no company signal)
    """
    q_lower = question.lower()
    has_macro = any(term in q_lower for term in _MACRO_TRIGGER_TERMS)
    if not has_macro:
        return False
    return any(sig in q_lower for sig in _MACRO_CROSS_COMPANY_SIGNALS)

_RISK_ASSESSMENT_PATTERNS: tuple = (
    "what are the risks", "biggest risk", "main risk", "key risk",
    "downside risk", "worst case", "what could go wrong",
    "regulatory risk", "competitive threat",
    # Phase 4 additions: geopolitical / transmission-channel questions
    # (e.g. R-P1: "What is the most likely earnings transmission channel…")
    "transmission channel", "earnings transmission", "earnings channel",
    "how should investors discount",
)

_COMPETITIVE_PATTERNS: tuple = (
    "competitive position", "market share", "moat", "versus",
    "compared to", "better than", "worse than", "vs ",
    "competitive advantage", "differentiat",
    # Phase 3 additions: exposure and custom-silicon phrasing that previously
    # fell through to investment_thesis (e.g. "How exposed is NVDA to custom chips?").
    "exposed to", "exposure to",
    "custom chip", "custom silicon", "custom asic",
    "hyperscaler", "in-house chip",
    "market share threat", "competitive threat",
    "market share loss", "losing share", "ceding share",
    "displacement risk", "platform displacement",
)


# ── Phase 4: fine-grained question-type intents ───────────────────────────────
# These six new categories are more specific than the existing five and are
# checked FIRST in _detect_question_intent so they take priority when their
# patterns match (e.g. "typical lag" is more specific than "hyperscaler").

_IMPLIED_GROWTH_PATTERNS: tuple = (
    "implied growth rate", "implied revenue", "implied 5-year", "implied 3-year",
    "market is pricing in", "market pricing in", "priced in growth",
    "what growth rate", "what revenue growth", "what cagr",
    "growth the market", "growth priced into",
    "what is the market pricing", "market prices in",
)

_HISTORICAL_PRECEDENT_PATTERNS: tuple = (
    "historical precedent", "prior cycle", "has any company ever",
    "comparable period", "when has", "what happened when",
    "historically when", "past precedent", "historical analog",
    "previous cycle", "what did any", "has ever sustained",
    "semiconductor precedent", "tech precedent", "historical example",
    "similar period", "historical analog", "analog to",
)

_METRIC_ORDERING_PATTERNS: tuple = (
    "deteriorates first", "declines first", "falls first",
    "which metric", "which of", "what degrades", "what cracks first",
    "ordering of", "which comes first", "first to decline",
    "which deteriorates", "most sharply", "which breaks first",
    "first and most",
)

_TIMING_LAG_PATTERNS: tuple = (
    "typical lag", "lag between", "what is the lag",
    "how many quarters", "how long until", "time between",
    "revenue lag", "capex lag", "decision to revenue",
    "lag from", "quarters before", "months before",
    "how long does it take", "resulting", "before the",
)

_QUANTITATIVE_THRESHOLD_PATTERNS: tuple = (
    "at what rate", "what loss rate", "what level causes",
    "at what point", "what threshold", "break-even", "breakeven",
    "what loan loss", "what charge-off", "quantify the",
    "eps impact", "roe impact", "bps impact",
    "quantify", "what revenue decline", "what margin decline",
    "at what growth", "at what multiple",
)

_SEGMENT_RANKING_PATTERNS: tuple = (
    "which segment", "widest moat", "rank the segment",
    "which business unit", "best segment", "strongest segment",
    "weakest segment", "widest economic moat",
    "rank in order", "most durable segment",
    "which division", "most protected",
    # Detects phrasing like "widest moat — Productivity, Intelligent Cloud…"
    "moat —", "moat—",
)


def _detect_question_intent(question: str) -> str:
    """Classify the user's question into a fine-grained intent.

    Returns one of (in priority order):
      'implied_growth_rate'  — "What growth rate does the current multiple price in?"
      'timing_lag'           — "What is the typical lag between capex and revenue?"
      'quantitative_threshold' — "At what loss rate does this impact EPS materially?"
      'metric_ordering'      — "Which metric deteriorates first in a recession?"
      'segment_ranking'      — "Which segment has the widest moat?"
      'historical_precedent' — "What historical precedent exists for X?"
      'valuation_stance'     — "Is X overpriced?" / "Is X fairly valued?"
      'macro_cross_company'  — "How will the jobs report impact tech stocks but specifically Nvidia?" (Sprint 1 P1)
      'macro_sensitivity'    — "How would rates affect X?"
      'risk_assessment'      — "What are X's biggest risks?"
      'competitive_position' — "How does X compare to competitors?"
      'investment_thesis'    — default full-thesis intent

    The new six intents (Phase 4) are checked before the legacy five because
    they use more specific patterns that would otherwise fall through to a
    coarser category (e.g. "hyperscaler" triggering competitive_position
    when the question is really about timing lags).

    Used to drive depth allocation, evidence retrieval, and answer framing.
    """
    q = question.lower()

    # ── Phase 4 intents — checked first (most specific) ──────────────────────
    if any(p in q for p in _IMPLIED_GROWTH_PATTERNS):
        return "implied_growth_rate"
    if any(p in q for p in _TIMING_LAG_PATTERNS):
        return "timing_lag"
    if any(p in q for p in _QUANTITATIVE_THRESHOLD_PATTERNS):
        return "quantitative_threshold"
    if any(p in q for p in _METRIC_ORDERING_PATTERNS):
        return "metric_ordering"
    if any(p in q for p in _SEGMENT_RANKING_PATTERNS):
        return "segment_ranking"
    if any(p in q for p in _HISTORICAL_PRECEDENT_PATTERNS):
        return "historical_precedent"

    # ── Legacy intents — checked after Phase 4 ───────────────────────────────
    if any(p in q for p in _VALUATION_STANCE_PATTERNS):
        return "valuation_stance"
    # Sprint 1 P1: macro_cross_company is more specific than macro_sensitivity —
    # check it first so "how will jobs report affect NVDA specifically" gets the
    # sequenced macro→company DA instead of the generic macro template.
    if _is_macro_cross_company(question):
        return "macro_cross_company"
    if any(p in q for p in _MACRO_SENSITIVITY_PATTERNS):
        return "macro_sensitivity"
    if any(p in q for p in _RISK_ASSESSMENT_PATTERNS):
        return "risk_assessment"
    if any(p in q for p in _COMPETITIVE_PATTERNS):
        return "competitive_position"
    return "investment_thesis"


def _run_investment_pipeline(
    company: CompanyContext,
    question: str,
    request_id: str,
) -> AgentAnswerResponse:
    """Run the full 5-agent investment pipeline for a detected company.

    Retrieves market + FRED evidence, partitions it across the 5 specialist
    agents, synthesizes an InvestmentThesis, and returns an AgentAnswerResponse.

    Parameters
    ----------
    company    : Detected and normalised CompanyContext.
    question   : Original user question text.
    request_id : Unique ID for this request (already generated by the caller).

    Returns
    -------
    AgentAnswerResponse with pipeline="investment_thesis".
    """
    ticker = company.ticker
    _pipeline_t0 = time.time()

    # ── Question intent detection ─────────────────────────────────────────────
    # Classify the user's question before evidence retrieval so that
    # valuation_stance questions get extra FMP evidence appended after the
    # standard cap.  This intent flows through the entire pipeline.
    _t_intent = time.time()
    question_intent = _detect_question_intent(question)
    print(
        f"[TIMING] [{ticker}] intent_detection={time.time()-_t_intent:.2f}s "
        f"question_intent={question_intent!r}"
    )

    # ── Evidence retrieval (7-task parallel pool) ────────────────────────────
    # Previously `retrieve_market_evidence` was called as ONE parallel task but
    # internally made 4 sequential HTTP calls (FMP→SEC→NewsAPI co→NewsAPI macro)
    # = 12-16s wall time.  Now each provider is its own independent task in a
    # 7-worker pool.  Wall time = max(slowest provider) ≈ 4-8s instead of
    # 12-16s.  Saves ~6-10s, bringing total pipeline under the 61s ceiling:
    #   evidence(8s) + agents(15s) + synthesis(30s) + post(3s) = 56s.
    _t_evidence = time.time()
    detected_topics = _detect_topics(question)

    def _fetch_fmp():
        try:
            return _fmp_provider.fetch_company_evidence(ticker) or []
        except Exception as _e:
            logger.warning("[router] fmp evidence failed for %s: %r", ticker, _e)
            return []

    def _fetch_sec():
        try:
            return _sec_provider.fetch_recent_filings(ticker) or []
        except Exception as _e:
            logger.warning("[router] sec evidence failed for %s: %r", ticker, _e)
            return []

    def _fetch_news_company():
        try:
            return _news_provider.fetch_company_news(ticker) or []
        except Exception as _e:
            logger.warning("[router] news/company failed for %s: %r", ticker, _e)
            return []

    def _fetch_news_macro():
        try:
            return _news_provider.fetch_macro_news(detected_topics) or []
        except Exception as _e:
            logger.warning("[router] news/macro failed: %r", _e)
            return []

    def _fetch_fred_evidence():
        return retrieve_general_finance_evidence(question)

    def _fetch_valuation_ratios():
        try:
            return fetch_valuation_ratios(ticker) or []
        except Exception as _e:
            logger.warning("[router] fetch_valuation_ratios failed for %s: %r", ticker, _e)
            return []

    def _fetch_analyst_estimates():
        try:
            return fetch_analyst_estimates(ticker) or []
        except Exception as _e:
            logger.warning("[router] fetch_analyst_estimates failed for %s: %r", ticker, _e)
            return []

    _ev_tasks = {
        "fmp":       _fetch_fmp,
        "sec":       _fetch_sec,
        "news_co":   _fetch_news_company,
        "news_macro":_fetch_news_macro,
        "fred":      _fetch_fred_evidence,
        "valuation": _fetch_valuation_ratios,
        "estimates": _fetch_analyst_estimates,
    }
    _ev_results: dict = {}
    try:
        with ThreadPoolExecutor(max_workers=7) as _ev_pool:
            _ev_futures = {k: _ev_pool.submit(fn) for k, fn in _ev_tasks.items()}
        for k, fut in _ev_futures.items():
            try:
                _ev_results[k] = fut.result()
            except Exception as _e:
                logger.warning("[router] evidence task %s failed: %r", k, _e)
                _ev_results[k] = []
    except Exception as _pool_exc:
        logger.warning("[router] evidence pool failed (%r) — falling back to sequential", _pool_exc)
        for k, fn in _ev_tasks.items():
            try:
                _ev_results[k] = fn()
            except Exception as _e:
                _ev_results[k] = []

    _fmp_ev:     list = _ev_results.get("fmp",       [])
    _sec_ev:     list = _ev_results.get("sec",       [])
    _news_co:    list = _ev_results.get("news_co",   [])
    _news_macro: list = _ev_results.get("news_macro",[])
    market_evidence: list = _fmp_ev + _sec_ev + _news_co + _news_macro
    fred_evidence:   list = _ev_results.get("fred",      [])
    _val_ratios:     list = _ev_results.get("valuation", [])
    _analyst_ests:   list = _ev_results.get("estimates", [])
    evidence = market_evidence + fred_evidence + _val_ratios + _analyst_ests

    print(
        f"[TIMING] [{ticker}] evidence_retrieval(7-parallel)={time.time()-_t_evidence:.2f}s "
        f"fmp={len(_fmp_ev)} sec={len(_sec_ev)} "
        f"news_co={len(_news_co)} news_macro={len(_news_macro)} "
        f"fred={len(fred_evidence)} val_ratios={len(_val_ratios)} "
        f"estimates={len(_analyst_ests)} total={len(evidence)}"
    )

    # ── Company knowledge profile ─────────────────────────────────────────────
    profile = get_profile_for_company(company)
    print(
        f"[DIAG] INVESTMENT PIPELINE [{ticker}]: "
        f"profile={'found' if profile else 'not_found'}"
    )

    # ── Evidence partitioning ─────────────────────────────────────────────────
    partition = partition_evidence(evidence, company)

    # ── Phase 4 (Option B): Q-First question answering pass ───────────────────
    # Generate a direct_answer BEFORE the thesis synthesis runs.  This call
    # uses the verbatim question + CompanyKnowledgeProfile + evidence to produce
    # a specific 4-sentence answer that is NOT derived from the conviction thesis.
    # The pre-synthesized answer is then passed to synthesize_thesis, which
    # injects it into the synthesis prompt and overwrites the synthesized
    # direct_answer field with it post-synthesis.
    #
    # For investment_thesis and business_model intents the Q-First pass adds only
    # marginal value (the synthesis mandates are already adequate) — but it runs
    # in the same thread pool as the 5 agents so there is no wall-time cost.
    # On failure it returns "" and synthesis falls back to mandate-only mode.
    from ..investment_agents.question_answerer_agent import run_question_answerer

    # ── Specialist agents + Q-First (parallel execution) ─────────────────────
    # The five investment agents are stateless and mutually independent — each
    # reads from its own evidence partition and calls the OpenAI API separately.
    # Running them in a thread pool cuts the agent-pipeline wall time from
    # ~20-25 s (sequential × 5) to ~5-8 s (parallel, bound by the slowest call).
    # Q-First runs as a 6th task in the same pool; it adds no additional latency
    # since the bottleneck is the slowest of the 5 agents.
    #
    # Fallback: if the thread pool itself raises, we re-run sequentially so no
    # request ever fails purely because of the parallelism mechanism.
    _t_agents = time.time()
    print(f"[TIMING] [{ticker}] starting 6 parallel agents (agent_model used by model_client)")

    from ..schemas import ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment

    def _run_valuation():
        return run_valuation_agent(
            company, partition.valuation,
            request_id=request_id, profile=profile,
            question_intent=question_intent,
            question=question,
        )

    def _run_macro():
        return run_investment_macro_agent(
            company, partition.macro,
            request_id=request_id, profile=profile,
            question_intent=question_intent,
            question=question,
        )

    def _run_risk():
        return run_risk_agent(
            company, partition.risk,
            request_id=request_id, profile=profile,
            question_intent=question_intent,
            question=question,
        )

    def _run_market():
        return run_market_agent(
            company, partition.market,
            request_id=request_id, profile=profile,
            question_intent=question_intent,
            question=question,
        )

    def _run_quality():
        return run_quality_agent(
            company, partition.quality,
            request_id=request_id, profile=profile,
            question_intent=question_intent,
            question=question,
        )

    def _run_question_answerer():
        return run_question_answerer(
            question=question,
            intent=question_intent,
            company=company,
            profile=profile,
            evidence=evidence,
        )

    _agent_tasks = {
        "valuation":          _run_valuation,
        "macro":              _run_macro,
        "risk":               _run_risk,
        "market":             _run_market,
        "quality":            _run_quality,
        "question_answerer":  _run_question_answerer,  # Phase 4 Q-First
    }
    _agent_defaults = {
        "valuation":         ValuationView(summary="Valuation analysis unavailable.", confidence=0.0),
        "macro":             MacroSensitivity(overall="Macro analysis unavailable.", confidence=0.0),
        "risk":              RiskProfile(overall="Risk analysis unavailable.", confidence=0.0),
        "market":            MarketContext(overall="Market context unavailable.", confidence=0.0),
        "quality":           QualityAssessment(overall="Quality assessment unavailable.", confidence=0.0),
        "question_answerer": "",  # Q-First default: empty string (fallback to mandate-only)
    }

    try:
        with ThreadPoolExecutor(max_workers=6) as _pool:
            _futures: dict[str, Future] = {
                name: _pool.submit(fn)
                for name, fn in _agent_tasks.items()
            }
        _agent_results = {}
        for name, fut in _futures.items():
            try:
                _agent_results[name] = fut.result()
            except Exception as exc:
                logger.warning("[router] %s_agent failed for %s: %r", name, ticker, exc)
                _agent_results[name] = _agent_defaults[name]
    except Exception as _pool_exc:
        # Thread pool failure — fall back to sequential execution
        logger.warning(
            "[router] parallel agent pool failed for %s (%r) — falling back to sequential",
            ticker, _pool_exc,
        )
        _agent_results = {}
        for name, fn in _agent_tasks.items():
            try:
                _agent_results[name] = fn()
            except Exception as exc:
                logger.warning("[router] %s_agent failed for %s: %r", name, ticker, exc)
                _agent_results[name] = _agent_defaults[name]

    valuation            = _agent_results["valuation"]
    macro                = _agent_results["macro"]
    risk                 = _agent_results["risk"]
    market               = _agent_results["market"]
    quality              = _agent_results["quality"]
    pre_synthesized_answer = _agent_results.get("question_answerer", "") or ""

    _agents_elapsed = time.time() - _t_agents
    print(
        f"[TIMING] [{ticker}] parallel_agents={_agents_elapsed:.2f}s "
        f"pre_synthesized_answer={'set' if pre_synthesized_answer else 'empty'} "
        f"({len(pre_synthesized_answer)} chars) "
        f"elapsed_so_far={time.time()-_pipeline_t0:.2f}s"
    )
    agents_run = ["valuation", "macro", "risk", "market", "quality", "question_answerer"]

    # ── Thesis synthesis ──────────────────────────────────────────────────────
    _t_synthesis = time.time()
    # Load prior snapshot for historical reasoning (fire-and-forget on failure)
    prior_snapshot = None
    try:
        prior_snapshot = watchlist_service.get_latest_snapshot(ticker)
    except Exception as exc:
        logger.debug("[router] prior snapshot load failed for %s: %r", ticker, exc)

    try:
        thesis = synthesize_thesis(
            company=company,
            valuation=valuation,
            macro=macro,
            risk=risk,
            market=market,
            quality=quality,
            evidence=evidence,
            profile=profile,
            original_user_question=question,
            question_intent=question_intent,
            prior_snapshot=prior_snapshot,
            pre_synthesized_answer=pre_synthesized_answer,
        )
    except Exception as exc:
        logger.warning("[router] synthesize_thesis failed for %s: %r", ticker, exc)
        from ..schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker=ticker,
            company_name=company.company_name,
            bull_thesis="Synthesis unavailable.",
            bear_thesis="Synthesis unavailable.",
            conclusion="Could not synthesize an investment thesis.",
            confidence_score=0.0,
            key_drivers=[],
            key_risks=[],
        )

    print(
        f"[TIMING] [{ticker}] synthesis={time.time()-_t_synthesis:.2f}s "
        f"total_pipeline={time.time()-_pipeline_t0:.2f}s"
    )

    # ── Stamp question intent + propagate valuation stance ───────────────────
    # Ensure question_intent is always on the thesis so the frontend / API
    # consumers can branch on it without re-deriving it.
    thesis.question_intent = question_intent
    # When the user asked a valuation stance question and the valuation agent
    # produced an explicit verdict, promote it to the top-level thesis field.
    if question_intent == "valuation_stance" and getattr(valuation, "valuation_stance", ""):
        thesis.valuation_stance = valuation.valuation_stance

    # ── Thesis memory — snapshot + diff + alert ───────────────────────────────
    # Save snapshot, run diff against prior, emit MaterialChangeEvent if material.
    # Backfill diff results onto thesis so the API response carries thesis_trend,
    # what_changed, and change_drivers for the frontend "What Changed" section.
    # Fire-and-forget: failure here must NEVER fail the API response.
    try:
        _change_event, _diff = watchlist_service.process_new_thesis(thesis)
        if _diff is not None:
            thesis.thesis_trend   = _diff.thesis_trend or "unclear"
            thesis.what_changed   = list(_diff.what_changed or [])
            thesis.change_drivers = list(_diff.change_drivers or [])
    except Exception as exc:
        logger.warning("[router] process_new_thesis failed for %s: %r", ticker, exc)

    try:
        thesis_dict = thesis.model_dump()
    except Exception:
        thesis_dict = thesis.dict()

    # ── [PRODUCTION_SANITIZE] Strip confidence_reasoning from API response ─────
    # confidence_reasoning is an internal telemetry field — a raw diagnostic wall
    # produced by the conviction modeler.  It must NEVER appear in production API
    # responses: it contains internal ontology labels, dimension field names,
    # GAP_* codes, and model-internal vocabulary that should not be visible to
    # end users or frontend consumers.
    #
    # The field is retained on the thesis object for in-process logging (see the
    # [BACKEND_FINAL_RESPONSE] log below) but is removed from the serialized dict
    # before it is embedded in the API response payload.
    #
    # DEV exposure: the raw confidence_reasoning is still accessible in server logs
    # and the [LIVE_CONFIDENCE_AUDIT] debug panel (which reads from rawPayload before
    # this strip fires — no, rawPayload IS the response dict, so it will be absent
    # there too, which is correct: DEV should read it from server logs, not UI).
    _raw_reasoning_for_log = thesis_dict.get("confidence_reasoning", "")
    thesis_dict["confidence_reasoning"] = ""   # blank — never None to keep schema valid

    # ── [BACKEND_FINAL_RESPONSE] — truth-path telemetry at serialization point ──
    # This log fires at the exact moment model_dump() converts InvestmentThesis
    # to a dict for the API response. If this log shows the right values but the
    # frontend still shows 65%, the problem is in the proxy, the Next.js route,
    # the frontend fetch handler, or the extractInvestmentThesis function.
    # Use the authoritative score_source stamped by synthesize_thesis (Phase 5g).
    # Falls back to the inline derivation if the field is absent (e.g. stale object).
    # Phase 6: use the stamped score_source field directly.
    # The old fallback derivation used `!= "actionable thesis"` which was wrong —
    # "actionable thesis" is now the correct matrix label for durable compounders.
    _score_source_diag = getattr(thesis, "score_source", None) or (
        "conviction_modeler" if bool(thesis.conviction_dimensions)
        else "llm_raw_preserved"
    )
    logger.info(
        "[BACKEND_FINAL_RESPONSE] ticker=%s "
        "confidence_score=%.4f "
        "setup_label=%r "
        "score_source=%s "
        "fragility_mult=%.4f "
        "asymmetry_mult=%.4f "
        "conviction_dims=%d "
        "confidence_reasoning_snippet=%r",
        ticker,
        thesis.confidence_score,
        thesis.setup_label,
        _score_source_diag,
        thesis.fragility_multiplier_applied,
        thesis.asymmetry_multiplier_applied,
        len(thesis.conviction_dimensions or {}),
        (_raw_reasoning_for_log or "")[:80],   # pre-strip value for log only
    )
    # [HEADLINE_CONFIDENCE_SOURCE] — also echoed here at the router serialization
    # boundary so the source is visible in a single log stream without needing
    # to cross-reference thesis_synthesizer logs.
    _used_legacy_formatter = _score_source_diag == "llm_raw_preserved"
    _reasoning_snippet = (_raw_reasoning_for_log or "")[:80].lower()
    _has_legacy_phrase = any(
        p in _reasoning_snippet for p in [
            "limited evidence coverage",
            "framework is sound",
            "data is thin",
        ]
    )
    print(
        f"[BACKEND_FINAL_RESPONSE] [{ticker}] "
        f"confidence={thesis.confidence_score:.4f} "
        f"setup_label={thesis.setup_label!r} "
        f"score_source={_score_source_diag} "
        f"fragility_mult={thesis.fragility_multiplier_applied:.4f} "
        f"conviction_dims={len(thesis.conviction_dimensions or {})} "
        f"reasoning_len={len(_raw_reasoning_for_log or '')} "
        f"[PRODUCTION_SANITIZE] confidence_reasoning=STRIPPED "
        f"[HEADLINE_CONFIDENCE_SOURCE] used_legacy_formatter={_used_legacy_formatter} "
        f"hard_fail_phrase={_has_legacy_phrase} "
        f"one_sentence_thesis={thesis.one_sentence_thesis!r:.60}"
    )

    # ── [DEPLOYMENT PROOF] backend_version in every thesis response ──────────
    # Temporary field — lets the frontend confirm the live backend is running
    # Phase 6 matrix conviction code by reading answer.backend_version.
    # If this field is missing from the live API response, the deployed process
    # is pre-matrix.  Remove once Render deploy is confirmed.
    try:
        from ..services.conviction_modeler import CONVICTION_SCHEMA_VERSION as _CSV
        _backend_version = f"matrix-conviction-v1/{_CSV}"
    except Exception:
        _backend_version = "matrix-conviction-v1/IMPORT_ERROR"

    return AgentAnswerResponse(
        company=ticker,
        request_id=request_id,
        agents_used=agents_run + ["thesis_synthesizer"],
        answer={
            "investment_thesis": thesis_dict,
            "backend_version":   _backend_version,   # [DEPLOYMENT PROOF]
        },
        routing={
            "pipeline": "investment_thesis",
            "detected_ticker": ticker,
            "detected_company": company.company_name,
            "evidence_count": len(evidence),
        },
    )


def route_question(request: QuestionRequest) -> AgentAnswerResponse:
    """Classify a question and route it to appropriate agent(s) with metadata.

    Non-company queries (empty company_name, or intent != company_analysis)
    are handled by the general finance agent — a single focused LLM call
    that returns a direct answer, elaboration bullets, and caveats.  The
    full company-analysis pipeline (equity/macro/synthesizer) is NOT
    invoked for these queries.

    Company queries flow through the existing keyword-based classifier and
    specialist agent pipeline unchanged.
    """
    # ── Company route check (text-based detection) ───────────────────────────
    # Run BEFORE the is_general gate so that questions like
    # "How would higher rates affect Apple stock?" route correctly even when
    # the frontend sends an empty company_name field.
    #
    # Uses resolve_entity() for structured confidence + observability:
    #   • high confidence (>= 0.72) → invest pipeline
    #   • not found but has candidates → graceful "Did you mean?" response
    #   • not found, no candidates → fall through to general finance
    _text_detected_company: Optional[CompanyContext] = None
    _entity_resolution = None
    if not request.company_name.strip():
        # Only run text detection when the frontend did not supply a company.
        try:
            _entity_resolution = resolve_entity(request.question)
            logger.info(
                json.dumps({
                    "event": "entity_resolution",
                    "raw_query": request.question[:120],
                    "entity": _entity_resolution.context.ticker if _entity_resolution.context else None,
                    "confidence": _entity_resolution.confidence,
                    "method": _entity_resolution.method,
                    "matched_text": _entity_resolution.matched_text,
                    "candidates": [t for t, _, _ in (_entity_resolution.candidates or [])],
                })
            )
            if _entity_resolution.context is not None:
                # Hard confidence gate — always route exact_ticker (1.0) and
                # alias_exact (0.95) matches.  For fuzzy_token matches, only
                # route when confidence meets MINIMUM_ROUTE_CONFIDENCE (0.85).
                # Below that threshold the match is ambiguous: surface candidates
                # via the "Did you mean?" flow instead of silently running the
                # wrong company's investment pipeline.
                _meets_threshold = (
                    _entity_resolution.method in ("exact_ticker", "alias_exact")
                    or _entity_resolution.confidence >= MINIMUM_ROUTE_CONFIDENCE
                )
                if _meets_threshold:
                    _text_detected_company = _entity_resolution.context
                    if _entity_resolution.confidence < 0.90:
                        logger.warning(
                            "[router] medium-confidence entity resolution: %s (%.2f via %s) "
                            "— proceeding with investment pipeline",
                            _entity_resolution.context.ticker,
                            _entity_resolution.confidence,
                            _entity_resolution.method,
                        )
                else:
                    # Fuzzy match below threshold — treat as unresolved so the
                    # "Did you mean?" path fires below.
                    logger.warning(
                        "[router] fuzzy match below routing threshold: "
                        "%s (%.2f via %s, threshold=%.2f) — demoting to candidates",
                        _entity_resolution.context.ticker,
                        _entity_resolution.confidence,
                        _entity_resolution.method,
                        MINIMUM_ROUTE_CONFIDENCE,
                    )
                    # Promote the low-confidence match as the top candidate
                    # so it appears in the "Did you mean?" suggestion.
                    if not _entity_resolution.candidates:
                        info = _entity_resolution.context
                        _entity_resolution.candidates = [
                            (info.ticker, info.company_name, _entity_resolution.confidence)
                        ]
                    _entity_resolution.context = None
        except Exception as _det_exc:
            logger.warning("[router] entity resolution failed: %r", _det_exc)
            _text_detected_company = None

    _detected_ticker = (
        _text_detected_company.ticker if _text_detected_company else request.company_name.strip() or None
    )
    _has_intent = _has_investment_intent(request.question)

    logger.debug(
        "[router] route_check frontend_company=%r detected=%r conf=%.2f has_intent=%s",
        request.company_name,
        _detected_ticker,
        _entity_resolution.confidence if _entity_resolution else 0.0,
        _has_intent,
    )

    # ── Fast path: explicit company_name + investment intent ─────────────────
    # When the caller supplies a non-empty company_name and the question has
    # investment intent, resolve the company directly and route to the full
    # investment pipeline without the text-detection detour.
    #
    # Why this is needed: the text-detection block above (lines 1118-1175) is
    # intentionally skipped when company_name is non-empty, so _text_detected_company
    # stays None and the investment pipeline is never reached via the existing
    # gate at line 1201.  Questions containing competitor names would therefore
    # fall through to the old keyword-routing path and receive a template equity
    # analysis that ignores the specific question asked.
    #
    # This block only fires for company_analysis intent.  market_question,
    # investing_education, portfolio_question, and general_fallback intents are
    # excluded so they continue to reach the general-finance agent as expected.
    _NON_COMPANY_INTENTS = frozenset({
        "market_question", "investing_education", "portfolio_question", "general_fallback"
    })
    if (
        request.company_name.strip()
        and _has_intent
        and request.intent not in _NON_COMPANY_INTENTS
    ):
        _explicit_company = detect_company(request.company_name.strip())
        if _explicit_company is not None:
            request_id = str(uuid.uuid4())
            logger.info(
                json.dumps({
                    "event": "company_route_explicit",
                    "request_id": request_id,
                    "company_name": request.company_name,
                    "detected_ticker": _explicit_company.ticker,
                    "question": request.question[:120],
                })
            )
            return _run_investment_pipeline(
                company=_explicit_company,
                question=request.question,
                request_id=request_id,
            )

    # Route to full investment pipeline when a company is detected from question
    # text AND the question has investment intent — OR when the entity was
    # resolved with high confidence (exact ticker or alias match), which
    # covers bare queries like "ASML", "Visa", "LLY", "NVO" that carry no
    # investment-signal keywords but are unambiguously company references.
    # Fuzzy matches still require explicit investment intent to avoid routing
    # on incidental company-name mentions in macro questions.
    _is_high_conf_entity = (
        _entity_resolution is not None
        and _entity_resolution.method in ("exact_ticker", "alias_exact")
    )
    if _text_detected_company is not None and (_has_intent or _is_high_conf_entity):
        request_id = str(uuid.uuid4())
        logger.info(
            json.dumps({
                "event": "company_route_detected",
                "request_id": request_id,
                "detected_ticker": _text_detected_company.ticker,
                "resolution_method": _entity_resolution.method if _entity_resolution else "unknown",
                "resolution_confidence": _entity_resolution.confidence if _entity_resolution else 1.0,
                "question": request.question,
            })
        )
        return _run_investment_pipeline(
            company=_text_detected_company,
            question=request.question,
            request_id=request_id,
        )

    # ── Graceful "Did you mean?" fallback ────────────────────────────────────
    # When entity resolution failed (confidence 0.0) but we have candidate
    # matches, return a structured suggestion response instead of falling
    # silently to a generic general-finance answer.
    #
    # Minimum confidence guard (added 2026-06-08):
    # Only fire Did You Mean when at least one candidate clears 0.70.
    # Candidates below that threshold are noise matches where common English
    # words (e.g. "recent", "to us") fuzzy-match company aliases at the
    # 0.55 collection cutoff.  Firing Did You Mean on such noise turns pure
    # macro queries ("jobs report", "Fed decision", "bank stocks") into
    # confusing company-suggestion responses.  Legitimate typo cases
    # ("Nvidiaa", "Microsof", "Freeprot-McMoRan") always produce at least
    # one candidate above 0.70.
    _DYM_MIN_CONFIDENCE = 0.70
    _has_quality_candidates = (
        _entity_resolution is not None
        and any(score >= _DYM_MIN_CONFIDENCE for _, _, score in _entity_resolution.candidates)
    )
    if (
        _entity_resolution is not None
        and _entity_resolution.context is None
        and _has_intent
        and _has_quality_candidates
    ):
        request_id = str(uuid.uuid4())
        candidates = _entity_resolution.candidates[:3]
        logger.info(
            json.dumps({
                "event": "entity_resolution_suggestions",
                "request_id": request_id,
                "question": request.question,
                "suggestions": [(t, n) for t, n, _ in candidates],
            })
        )
        from ..schemas import GeneralFinanceAnswer as _GFA
        if candidates:
            suggestion_text = " or ".join(
                f"{name} ({ticker})" for ticker, name, _ in candidates
            )
            did_you_mean = _GFA(
                answer=(
                    f"The company could not be identified with sufficient confidence. "
                    f"Did you mean {suggestion_text}? "
                    f"Try entering the exact company name or ticker symbol (e.g. VRTX, NVO, ISRG)."
                ),
                bullets=[
                    f"{name} — ticker: {ticker}" for ticker, name, _ in candidates
                ],
                caveats=[
                    "Use the exact ticker symbol for reliable results (e.g. VRTX for Vertex Pharmaceuticals).",
                    "Company names are matched exactly — check spelling and try the full legal name.",
                ],
            )
        else:
            # No candidates at all — firm rejection, no hallucinated routing.
            did_you_mean = _GFA(
                answer=(
                    "The company name could not be confidently identified. "
                    "No close matches were found in the company database. "
                    "Please enter the exact company name or ticker symbol."
                ),
                bullets=[
                    "Use a ticker symbol for best results (e.g. AAPL, MSFT, NVDA, VRTX).",
                    "Check the spelling of the company name — partial or ambiguous names may not resolve.",
                    "If the company is not publicly listed in the US, it may not be in the current database.",
                ],
                caveats=[
                    "The system will not route to an unrelated company when confidence is low.",
                ],
            )
        return AgentAnswerResponse(
            company=request.company_name,
            request_id=request_id,
            agents_used=["entity_resolution_fallback"],
            answer={"general": did_you_mean.model_dump()},
            routing={
                "intent": "company_analysis",
                "pipeline": "entity_suggestion",
                "candidates": [(t, n) for t, n, _ in candidates],
            },
        )

    # ── General finance fast-path ─────────────────────────────────────────────
    # Triggered when the frontend sends an empty company_name (market questions,
    # investing education, portfolio questions) or explicitly signals a
    # non-company intent via the optional `intent` field.
    is_general = (
        not request.company_name.strip()
        or request.intent in (
            "market_question", "investing_education", "portfolio_question", "general_fallback"
        )
    )

    if is_general:
        request_id = str(uuid.uuid4())
        intent = request.intent or _detect_intent(request.question)
        logger.info(
            json.dumps({
                "event": "general_finance_query",
                "request_id": request_id,
                "intent": intent,
                "question": request.question,
            })
        )

        # ── Step 1: call agent ────────────────────────────────────────────────
        # general_fallback → open-ended LLM agent that answers any question
        # all other intents → specialist finance agent with intent-aware framing
        try:
            if intent == "general_fallback":
                result = run_general_fallback_agent(
                    question=request.question,
                    request_id=request_id,
                )
            else:
                result = run_general_finance_agent(
                    question=request.question,
                    intent=intent,
                    request_id=request_id,
                )
        except Exception as exc:
            logger.error(
                json.dumps({"event": "general_finance_error", "error": str(exc),
                            "request_id": request_id})
            )
            # Build a safe fallback object so the guard below always has
            # a concrete object to inspect — never a raw empty dict.
            from ..schemas import GeneralFinanceAnswer as _GFA  # local import to avoid circular
            result = _GFA(answer="", bullets=[], caveats=[])

        # ── Step 2: PRE-VALIDATION trace ─────────────────────────────────────
        print(
            f"[route_question] PRE-VALIDATION GENERAL ANSWER: "
            f"answer={result.answer!r} "
            f"bullets={result.bullets} "
            f"caveats={result.caveats}"
        )

        # ── Step 3: Fallback trigger check ───────────────────────────────────
        current_answer = (result.answer or "").strip()
        print(
            f"[route_question] FALLBACK TRIGGER CHECK: "
            f"answer={result.answer!r} "
            f"len={len(current_answer)} "
            f"bullets={result.bullets} "
            f"caveats={result.caveats}"
        )

        # ── Step 4: Apply fallbacks directly on the model object ─────────────
        # We mutate the model object BEFORE serialization so that no subsequent
        # model_dump / dict call can ever return the empty values.
        #
        # Evidence-gate rule (definitive):
        #   The agent stamps result.evidence_count with the number of FRED
        #   items it retrieved.  When evidence_count > 0 the LLM had real data
        #   in its prompt, so its answer is always kept UNLESS it is empty or
        #   shorter than 40 chars.  The generic-language gate (_is_generic_answer)
        #   is ONLY applied when evidence_count == 0 — i.e. when the agent fell
        #   back to pure conceptual reasoning with no live data.
        #
        # Trigger matrix:
        #   answer empty / len < 40          → always replace (too_short)
        #   evidence_count > 0, len ≥ 40     → keep answer  (evidence_backed)
        #   evidence_count == 0, generic txt → replace      (generic_language)
        #   evidence_count == 0, ok text     → keep answer  (ok)

        evidence_count: int = getattr(result, "evidence_count", 0)
        has_evidence: bool = evidence_count > 0

        print(
            f"[DIAG] ROUTER FALLBACK DECISION "
            f"evidence_count={evidence_count} "
            f"has_evidence={has_evidence} "
            f"answer_len={len(current_answer)}"
        )

        answer_needs_replacement: bool
        if not current_answer or len(current_answer) < 40:
            answer_needs_replacement = True
            reason = "too_short"
        elif has_evidence:
            # Agent had real FRED data — trust its answer unconditionally.
            answer_needs_replacement = False
            reason = "evidence_backed"
        else:
            # No evidence retrieved — apply the generic-language gate.
            answer_needs_replacement = _is_generic_answer(current_answer)
            reason = "generic_language" if answer_needs_replacement else "ok"

        print(
            f"[DIAG] ROUTER FALLBACK DECISION "
            f"evidence_count={evidence_count} "
            f"has_evidence={has_evidence} "
            f"reason={reason}"
        )

        if answer_needs_replacement:
            # Choose the best fallback answer:
            #   • yield question → _YIELD_FALLBACK_ANSWER (mentions specific
            #     FRED series: 10-Year, 2-Year, yield curve spread)
            #   • other topic   → _topic_aware_fallback() static text
            topics = _detect_topics(request.question)
            # Also catch bare "yields" queries whose normalized form contains
            # "yields" as a standalone token but doesn't match any compound
            # phrase in _TOPIC_KEYWORDS (e.g. "Why are yields rising?").
            _nq = _normalize_macro_query(request.question)
            _is_yield_q = (
                "yields" in topics
                or "yields" in _nq.split()
                or "yield" in _nq.split()
            )
            if _is_yield_q:
                fallback_answer = _YIELD_FALLBACK_ANSWER
                _fb_a, fallback_bullets, fallback_caveats = _topic_aware_fallback(
                    request.question
                )
            else:
                fallback_answer, fallback_bullets, fallback_caveats = _topic_aware_fallback(
                    request.question
                )
            print(
                f"[route_question] FALLBACK TRIGGERED ({reason}) — "
                f"original_answer={result.answer!r} "
                f"fallback={fallback_answer!r}"
            )
            logger.warning(
                json.dumps({
                    "event": "general_finance_empty_answer",
                    "reason": reason,
                    "request_id": request_id,
                    "original_answer": result.answer,
                    "fallback": fallback_answer,
                })
            )
            result.answer = fallback_answer
            # When we replace the answer, also replace bullets/caveats with
            # topic-matched versions so all three fields are coherent.
            if not result.bullets:
                result.bullets = fallback_bullets
            if not result.caveats:
                result.caveats = fallback_caveats

        if not result.bullets:
            print("[route_question] BULLETS FALLBACK TRIGGERED")
            _fb_answer, fb_bullets, _fb_caveats = _topic_aware_fallback(request.question)
            result.bullets = fb_bullets

        if not result.caveats:
            print("[route_question] CAVEATS FALLBACK TRIGGERED")
            _fb_answer, _fb_bullets, fb_caveats = _topic_aware_fallback(request.question)
            result.caveats = fb_caveats

        # ── Step 5: Serialize AFTER all fallbacks are applied ─────────────────
        # model_dump / dict is called here and only here — there is no later
        # serialization step that can overwrite the fallback values.
        try:
            answer_dict = result.model_dump()  # type: ignore[attr-defined]
        except Exception:
            answer_dict = result.dict()  # type: ignore[call-arg]

        # ── Step 6: Final sanity assertion before building the response ───────
        assert answer_dict.get("answer"), (
            f"[route_question] ASSERTION FAILED: answer_dict.answer is empty after fallback "
            f"— this should never happen. answer_dict={answer_dict}"
        )

        pipeline_label = "general_fallback" if intent == "general_fallback" else "general_finance"
        final_response = AgentAnswerResponse(
            company=request.company_name,
            request_id=request_id,
            agents_used=[pipeline_label],
            answer={"general": answer_dict},
            routing={"intent": intent, "pipeline": pipeline_label},
        )

        # ── Step 7: Final serialized trace ────────────────────────────────────
        print(
            f"[route_question] FINAL SERIALIZED GENERAL ANSWER:\n"
            f"  answer_dict={answer_dict}\n"
            f"  response.answer={final_response.answer}"
        )

        return final_response

    # ── Company analysis pipeline ─────────────────────────────────────────────
    # Enrich context so that prompts always receive operational grounding
    context = enrich_grounding_context(request.company_name, request.question, request.context)
    # Before classification, attempt to gather external evidence to
    # substantiate the grounding context.  Select evidence sources
    # based on the question and then build evidence into the context.
    try:
        evidence_decision = select_evidence_sources(request.question)
        selected_sources = evidence_decision.get("selected_sources", [])
    except Exception as exc:
        # If evidence selection fails, fall back to no sources and log the error.
        logger.error(json.dumps({"event": "evidence_selection_error", "error": str(exc)}))
        selected_sources = []
    try:
        # Derive symbol for FMP/SEC calls; fall back to company name when ticker is absent
        symbol = context.ticker or request.company_name
        context = build_evidence(request.company_name, symbol, request.question, selected_sources, context)
    except Exception as exc:
        logger.error(json.dumps({"event": "evidence_build_error", "error": str(exc)}))
        # Leave context unchanged if evidence building fails

    # Generate a unique request ID for logging
    request_id = str(uuid.uuid4())
    company = request.company_name
    # Classify question using the shared classifier
    routing_decision = classify_question(request.question)
    selected = routing_decision.get("selected_agents", [])

    # Routing is strictly selective.  Equity runs only when the router
    # classifies it as relevant.  If no agent is selected, equity is
    # treated as the sensible default for a company-analysis request,
    # but this is an explicit fallback — not an unconditional baseline.
    if not selected:
        selected = ["equity"]
    specialized = [a for a in selected if a != "equity"]

    # Initialize outputs to empty schemas.  Each agent is only invoked
    # when it appears in the routing decision.
    equity      = EquityAnalysis()       # type: ignore[name-defined]
    macro       = MacroAnalysis()
    opportunity = OpportunityAnalysis()
    research    = ResearchAnalysis()
    education   = EducationAnalysis()
    accounting  = AccountingAnalysis()

    # Run each selected agent explicitly.  No agent executes unless it is
    # in the ``selected`` list.
    for agent in selected:
        if agent == "equity":
            try:
                equity = run_equity_agent(company, context=context,
                                          user_question=request.question,
                                          request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "equity",
                                          "error": str(exc), "request_id": request_id}))
                equity = EquityAnalysis()  # type: ignore[name-defined]
        elif agent == "macro":
            try:
                macro = run_macro_agent(company, context=context, request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "macro", "error": str(exc), "request_id": request_id}))
                macro = MacroAnalysis()
        elif agent == "opportunity":
            try:
                opportunity = run_opportunity_agent(company, context=context, request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "opportunity", "error": str(exc), "request_id": request_id}))
                opportunity = OpportunityAnalysis()
        elif agent == "research":
            try:
                research = run_research_agent(company, context=context, request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "research", "error": str(exc), "request_id": request_id}))
                research = ResearchAnalysis()
        elif agent == "education":
            try:
                education = run_education_agent(company, context=context, request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "education", "error": str(exc), "request_id": request_id}))
                education = EducationAnalysis()
        elif agent == "accounting":
            try:
                accounting = run_accounting_agent(company, context=context, request_id=request_id)
            except Exception as exc:
                logger.error(json.dumps({"event": "agent_error", "agent": "accounting", "error": str(exc), "request_id": request_id}))
                accounting = AccountingAnalysis()

    # Log routing decision
    try:
        logger.info(
            json.dumps({
                "event": "question_routed",
                "request_id": request_id,
                "company": company,
                "question": request.question,
                "routing": routing_decision,
            })
        )
    except Exception:
        pass

    # Helper to convert Pydantic models to plain dictionaries in a
    # version‑agnostic way.  Use ``model_dump`` when available (pydantic
    # v2) to avoid deprecation warnings; fall back to ``dict`` for v1.
    def _dump(model: Any) -> Dict[str, Any]:
        try:
            return model.model_dump()  # type: ignore[attr-defined]
        except Exception:
            return model.dict()  # type: ignore[call-arg]

    # If exactly one specialized agent besides equity is selected, return its
    # output combined with equity.  The ordering of specialized list
    # corresponds to classification priority.
    if len(specialized) == 1:
        agent = specialized[0]
        if agent == "macro":
            answer = {
                "equity": _dump(equity),
                "macro": _dump(macro),
            }
        elif agent == "opportunity":
            answer = {
                "equity": _dump(equity),
                "opportunity": _dump(opportunity),
            }
        elif agent == "research":
            answer = {
                "equity": _dump(equity),
                "research": _dump(research),
            }
        elif agent == "education":
            answer = {
                "equity": _dump(equity),
                "education": _dump(education),
            }
        elif agent == "accounting":
            answer = {
                "equity": _dump(equity),
                "accounting": _dump(accounting),
            }
        else:
            answer = {"equity": _dump(equity)}
        return AgentAnswerResponse(
            company=company,
            request_id=request_id,
            agents_used=["equity", agent],
            answer=answer,
            routing=routing_decision,
        )

    # Otherwise run synthesizer to combine all selected outputs.  Catch
    # synthesizer failures and fall back to a safe SynthesisOutput.
    try:
        synthesis = run_synthesizer_agent(
            company,
            equity,
            macro,
            opportunity,
            research,
            education,
            accounting,
            context=context,
            request_id=request_id,
        )
        # Use model_dump to avoid deprecation warnings
        try:
            answer_dict = synthesis.model_dump()  # type: ignore[attr-defined]
        except Exception:
            answer_dict = synthesis.dict()  # type: ignore[call-arg]
    except Exception as exc:
        logger.error(json.dumps({"event": "agent_error", "agent": "synthesizer", "error": str(exc), "request_id": request_id}))
        synthesis = SynthesisOutput()  # type: ignore[name-defined]
        try:
            answer_dict = synthesis.model_dump()  # type: ignore[attr-defined]
        except Exception:
            answer_dict = synthesis.dict()  # type: ignore[attr-defined]

    return AgentAnswerResponse(
        company=company,
        request_id=request_id,
        agents_used=["equity"] + specialized,
        answer=answer_dict,
        routing=routing_decision,
    )