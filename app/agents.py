"""
Agent orchestration functions for the AI analyst backend.

Each function constructs a prompt using the templates in ``prompts.py``,
passes the prompt to the central model client, and returns a parsed
Pydantic model via the structured output utility.  All model
interactions flow through this module.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from pydantic import BaseModel  # for model_dump helper

from .prompts import (
    equity_prompt,
    macro_prompt,
    opportunity_prompt,
    research_prompt,
    education_prompt,
    accounting_prompt,
    synthesizer_prompt,
    general_finance_prompt,
    general_fallback_prompt,
    _TEMPORAL_MARKERS,
)
from .services.general_finance_evidence import (
    retrieve_general_finance_evidence,
    _detect_topics,
)
from .schemas import (
    GroundingContext,
    EquityAnalysis,
    MacroAnalysis,
    OpportunityAnalysis,
    ResearchAnalysis,
    EducationAnalysis,
    AccountingAnalysis,
    SynthesisOutput,
    GeneralFinanceAnswer,
    RetrievedEvidence,
)
from .structured_output import get_structured_response
from .model_client import model_client
from .config import settings


# ── Post-generation evidence quality guard ────────────────────────────────────

# Terms that indicate the answer actually used retrieved evidence rather than
# falling back to a generic conceptual explanation.  All lowercase — checked
# against a lowercased copy of the answer.
_EVIDENCE_TERMS = frozenset([
    "10-year treasury",
    "2-year treasury",
    "yield curve",
    "2s10s",
    "t10y2y",
    "fed funds",
    "federal funds",
    "fedfunds",
    "cpi",
    "consumer price",
    "unemployment",
    "unrate",
    "gdp",
    "gdpc1",
    "industrial production",
    "indpro",
    "dgs10",
    "dgs2",
])

# Yield-specific fallback answer injected when the LLM ignores yield evidence.
_YIELD_FALLBACK_ANSWER = (
    "Treasury yields are moving because investors are repricing the path of "
    "interest rates, inflation expectations, and growth risk. "
    "The key evidence to watch is the 10-year Treasury yield, the 2-year "
    "Treasury yield, and the 10-year minus 2-year yield curve spread, which "
    "together show how markets are pricing long-term rates, near-term Fed "
    "policy, and recession risk."
)

# Generic evidence fallback for non-yield topics.
_GENERIC_EVIDENCE_FALLBACK = (
    "The latest macro data shows mixed signals across key indicators. "
    "Watch the retrieved evidence above — including the Fed funds rate, "
    "CPI, unemployment rate, and GDP figures — for a clearer picture of "
    "where the economy and markets are headed."
)


def _is_yield_question(question: str, evidence: List[RetrievedEvidence]) -> bool:
    """Return True if the question + evidence are clearly about Treasury yields.

    Two paths to True:
    1. Topic detection marks the question as a yield question.
    2. The retrieved evidence contains Treasury / yield-curve data, which
       means the retrieval layer already classified it as a yield topic even
       if the raw question phrasing wasn't caught by keyword matching (e.g.
       "Why are yields moving right now?" uses bare "yields" with no
       "treasury" or "bond" companion word).
    """
    topics = _detect_topics(question)
    if "yields" in topics:
        return True
    # Check evidence titles for markers that only appear in yield-series data.
    # FRED yield titles all contain "Treasury" or "Maturity" (from _SERIES_META).
    _YIELD_TITLE_MARKERS = ("Treasury", "Constant Maturity", "yield curve", "T10Y2Y")
    for ev in evidence:
        if any(marker in ev.title for marker in _YIELD_TITLE_MARKERS):
            return True
    return False


def _enforce_evidence_usage(
    question: str,
    evidence: List[RetrievedEvidence],
    result: GeneralFinanceAnswer,
) -> GeneralFinanceAnswer:
    """Replace the answer with an evidence-grounded fallback if the LLM ignored evidence.

    Checks whether the answer field mentions at least one term from
    ``_EVIDENCE_TERMS``.  If it does not — meaning the model produced a
    generic conceptual answer despite having retrieved evidence — the answer
    is replaced with a fallback that names the correct evidence terms so the
    frontend always surfaces something meaningful.

    Bullets and caveats from the original LLM response are preserved.

    Parameters
    ----------
    question  : The original user question.
    evidence  : The evidence list that was injected into the prompt.
    result    : The GeneralFinanceAnswer returned by the LLM.

    Returns
    -------
    GeneralFinanceAnswer  (original if evidence was used, fallback if not)
    """
    if not evidence:
        return result  # no evidence → nothing to enforce

    answer_lower = result.answer.lower()
    used_evidence = any(term in answer_lower for term in _EVIDENCE_TERMS)

    print(f"[DIAG] POST-GEN GUARD: evidence_terms_found={used_evidence}")

    if used_evidence:
        return result  # answer already references evidence — pass

    # Answer failed the guard — substitute fallback
    fallback_answer = (
        _YIELD_FALLBACK_ANSWER
        if _is_yield_question(question, evidence)
        else _GENERIC_EVIDENCE_FALLBACK
    )

    print(
        f"[DIAG] POST-GEN GUARD: REPLACING answer — LLM ignored evidence. "
        f"yield_question={_is_yield_question(question, evidence)}"
    )

    return GeneralFinanceAnswer(
        answer=fallback_answer,
        bullets=result.bullets,
        caveats=result.caveats,
    )

# Load system prompt once for all agents.  If a custom path is provided
# via the environment variable, it will be loaded there; otherwise the
# default ``system_prompt.txt`` next to this module will be used.
from pathlib import Path


def _load_system_prompt() -> str:
    path_str = settings.system_prompt_file.strip() if settings.system_prompt_file else ""
    if path_str:
        candidate = Path(path_str)
    else:
        candidate = Path(__file__).resolve().parent / "system_prompt.txt"
    try:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


SYSTEM_PROMPT = _load_system_prompt()


def run_equity_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    user_question: Optional[str] = None,
    request_id: Optional[str] = None,
) -> EquityAnalysis:
    """Execute the Equity Analyst agent and return its structured output."""
    prompt = equity_prompt(company, context, user_question)
    return get_structured_response(
        prompt,
        EquityAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_macro_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> MacroAnalysis:
    prompt = macro_prompt(company, context)
    return get_structured_response(
        prompt,
        MacroAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_opportunity_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> OpportunityAnalysis:
    prompt = opportunity_prompt(company, context)
    return get_structured_response(
        prompt,
        OpportunityAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_research_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> ResearchAnalysis:
    prompt = research_prompt(company, context)
    return get_structured_response(
        prompt,
        ResearchAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_education_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> EducationAnalysis:
    prompt = education_prompt(company, context)
    return get_structured_response(
        prompt,
        EducationAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_accounting_agent(
    company: str,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> AccountingAnalysis:
    prompt = accounting_prompt(company, context)
    return get_structured_response(
        prompt,
        AccountingAnalysis,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )


def run_general_finance_agent(
    question: str,
    intent: Optional[str] = None,
    request_id: Optional[str] = None,
) -> GeneralFinanceAnswer:
    """Execute the general finance Q&A agent.

    Used for non-company intents: market_question, investing_education,
    and portfolio_question.  The agent:
      1. Retrieves grounding evidence via retrieve_general_finance_evidence().
      2. Injects that evidence into the prompt as a "Current Context" section.
      3. Calls the LLM and returns a structured GeneralFinanceAnswer.

    When no evidence is available (retrieve_general_finance_evidence returns []),
    the prompt falls back to conceptual reasoning exactly as before — no
    degradation in output quality.

    The company analysis pipeline (equity, macro, synthesizer) is NOT
    invoked by this agent.  No Buy/Hold/Avoid is produced.
    """
    print(f"[run_general_finance_agent] question={question!r} intent={intent!r}")

    # ── Step 1: Retrieve grounding evidence ──────────────────────────────────
    try:
        evidence = retrieve_general_finance_evidence(question)
    except Exception as exc:
        print(f"[run_general_finance_agent] evidence retrieval failed: {exc!r} — continuing without")
        evidence = []

    print(
        f"[run_general_finance_agent] evidence_count={len(evidence)} "
        f"titles={[e.title[:40] for e in evidence]}"
    )

    # ── Step 2: Build evidence-grounded prompt ────────────────────────────────
    prompt = general_finance_prompt(question, intent=intent, evidence=evidence or None)

    # ── Step 3: LLM call ──────────────────────────────────────────────────────
    result = get_structured_response(
        prompt,
        GeneralFinanceAnswer,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )

    print(
        f"[run_general_finance_agent] answer={result.answer!r:.120} "
        f"bullets_count={len(result.bullets)} "
        f"caveats_count={len(result.caveats)}"
    )

    # ── Step 4: Post-generation quality guard ────────────────────────────────
    result = _enforce_evidence_usage(question, evidence, result)

    # ── Step 5: Stamp evidence count for the router ───────────────────────────
    # route_question reads this to decide whether the generic-language fallback
    # gate should apply.  Set it AFTER the quality guard so it always reflects
    # how many FRED items were actually retrieved, regardless of whether the
    # guard replaced the answer.
    result.evidence_count = len(evidence)
    print(f"[run_general_finance_agent] evidence_count stamped on result: {result.evidence_count}")

    return result


def run_general_fallback_agent(
    question: str,
    request_id: Optional[str] = None,
) -> GeneralFinanceAnswer:
    """Execute the general fallback agent for unclassified questions.

    Used when a question does not clearly match any of the known finance
    intents (company_analysis, market_question, investing_education,
    portfolio_question).  Typical examples: broad economic questions,
    interdisciplinary questions ("How does AI affect productivity?"),
    historical/factual questions ("How often does the Fed meet?"), or
    conceptual questions ("What makes a company valuable?").

    Follows the same evidence-grounding pipeline as run_general_finance_agent:
      1. Retrieve evidence via retrieve_general_finance_evidence().
      2. Inject into the fallback prompt as "Current Context".
      3. Call LLM and return GeneralFinanceAnswer.

    Returns a GeneralFinanceAnswer so the same rendering and fallback
    enforcement logic applies as for run_general_finance_agent.
    """
    print(f"[run_general_fallback_agent] question={question!r}")

    # ── Step 1: Retrieve grounding evidence ──────────────────────────────────
    try:
        evidence = retrieve_general_finance_evidence(question)
    except Exception as exc:
        print(f"[run_general_fallback_agent] evidence retrieval failed: {exc!r} — continuing without")
        evidence = []

    print(
        f"[run_general_fallback_agent] evidence_count={len(evidence)} "
        f"titles={[e.title[:40] for e in evidence]}"
    )

    # ── Step 2: Build evidence-grounded prompt ────────────────────────────────
    prompt = general_fallback_prompt(question, evidence=evidence or None)

    # ── Step 3: LLM call ──────────────────────────────────────────────────────
    result = get_structured_response(
        prompt,
        GeneralFinanceAnswer,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )

    print(
        f"[run_general_fallback_agent] answer={result.answer!r:.120} "
        f"bullets_count={len(result.bullets)} "
        f"caveats_count={len(result.caveats)}"
    )

    # ── Step 4: Post-generation quality guard ────────────────────────────────
    result = _enforce_evidence_usage(question, evidence, result)

    # ── Step 5: Stamp evidence count for the router ───────────────────────────
    result.evidence_count = len(evidence)
    print(f"[run_general_fallback_agent] evidence_count stamped on result: {result.evidence_count}")

    return result


def run_synthesizer_agent(
    company: str,
    equity: EquityAnalysis,
    macro: MacroAnalysis,
    opportunity: OpportunityAnalysis,
    research: ResearchAnalysis,
    education: EducationAnalysis,
    accounting: AccountingAnalysis,
    context: Optional[GroundingContext] = None,
    request_id: Optional[str] = None,
) -> SynthesisOutput:
    # Use model_dump when available (pydantic v2) to avoid deprecation warnings; fall back to dict
    def _dump(model: BaseModel) -> Dict[str, Any]:  # type: ignore[valid-type]
        try:
            return model.model_dump()  # type: ignore[attr-defined]
        except Exception:
            return model.dict()  # type: ignore[call-arg]

    prompt = synthesizer_prompt(
        company,
        _dump(equity),
        _dump(macro),
        _dump(opportunity),
        _dump(research),
        _dump(education),
        _dump(accounting),
        context,
    )
    return get_structured_response(
        prompt,
        SynthesisOutput,
        model_client,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        system_prompt=SYSTEM_PROMPT,
        request_id=request_id,
    )