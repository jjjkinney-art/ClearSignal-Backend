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


def route_question(request: QuestionRequest) -> AgentAnswerResponse:
    """Classify a question and route it to appropriate agent(s) with metadata.

    This function performs context enrichment, classification, selective
    agent invocation, and synthesizer orchestration.  It returns a
    structured ``AgentAnswerResponse`` that includes routing metadata.
    Specialized agents are invoked only when selected by the classifier.
    """
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