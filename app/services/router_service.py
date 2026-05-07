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
import uuid
from typing import Dict, List, Any

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
        # Two triggers:
        #   a) answer is too short (< 40 chars) — LLM returned empty/minimal
        #   b) answer contains generic category language — LLM deflected instead
        #      of answering directly ("This is a macro question...", etc.)
        #
        # In both cases we replace with a topic-aware answer from
        # _topic_aware_fallback(), which pattern-matches against the question.
        answer_needs_replacement = (
            len(current_answer) < 40
            or _is_generic_answer(current_answer)
        )

        if answer_needs_replacement:
            fallback_answer, fallback_bullets, fallback_caveats = _topic_aware_fallback(
                request.question
            )
            reason = "too_short" if len(current_answer) < 40 else "generic_language"
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