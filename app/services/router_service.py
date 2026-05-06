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


def _build_answer_fallback(question: str, intent: str) -> str:
    """Return a non-empty, principled fallback answer string.

    Used when the LLM returns an empty or too-short answer field.  The
    fallback is intentionally general but topic-aware so it is never
    misleading.  It always contains at least 2 sentences.
    """
    q = question.strip().rstrip("?").lower()
    if intent == "investing_education":
        return (
            f"This question asks about a core investing concept related to '{q}'. "
            "In investing, understanding how these mechanisms work helps you evaluate "
            "opportunities and risks more clearly — the details depend on the specific "
            "context, but the underlying principles are well-established."
        )
    if intent == "portfolio_question":
        return (
            "Portfolio decisions depend on your time horizon, risk tolerance, and current "
            f"allocation — all of which affect how you should think about '{q}'. "
            "In general, diversification, rebalancing cadence, and position sizing are the "
            "key levers; the right answer for your situation depends on those specifics."
        )
    if intent == "general_fallback":
        return (
            f"'{q.capitalize()}' is a broad question that touches on economics, markets, "
            "or business fundamentals. "
            "The answer depends on context, but the underlying principles are "
            "well-understood — the key is knowing which forces are dominant at any given time."
        )
    # Default: market_question or unknown
    return (
        f"This is a macro or market question about '{q}'. "
        "Financial markets respond to a combination of economic data, central bank policy, "
        "and investor sentiment — the direction and magnitude of any effect depends on "
        "how those forces interact at the time."
    )


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
        if len(current_answer) < 40:
            fallback_text = _build_answer_fallback(request.question, intent)
            print(
                f"[route_question] FALLBACK TRIGGERED — "
                f"original_answer={result.answer!r} "
                f"fallback={fallback_text!r}"
            )
            logger.warning(
                json.dumps({
                    "event": "general_finance_empty_answer",
                    "request_id": request_id,
                    "original_answer": result.answer,
                    "fallback": fallback_text,
                })
            )
            result.answer = fallback_text

        if not result.bullets:
            print("[route_question] BULLETS FALLBACK TRIGGERED")
            result.bullets = [
                "This topic involves how financial markets or instruments work in practice.",
                "Understanding the mechanism helps investors make more informed decisions.",
                "Watch for changes in relevant indicators — they often signal shifts before prices move.",
            ]

        if not result.caveats:
            print("[route_question] CAVEATS FALLBACK TRIGGERED")
            result.caveats = [
                "Context matters — the general principle may apply differently depending on market conditions.",
                "Consider consulting a financial adviser for decisions specific to your situation.",
            ]

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