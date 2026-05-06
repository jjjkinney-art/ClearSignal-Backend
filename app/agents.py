"""
Agent orchestration functions for the AI analyst backend.

Each function constructs a prompt using the templates in ``prompts.py``,
passes the prompt to the central model client, and returns a parsed
Pydantic model via the structured output utility.  All model
interactions flow through this module.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
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
)
from .structured_output import get_structured_response
from .model_client import model_client
from .config import settings

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
    and portfolio_question.  The agent receives a purpose-built prompt
    that is intent-aware and returns a structured answer with a direct
    response paragraph, elaboration bullets, and honest caveats.

    The company analysis pipeline (equity, macro, synthesizer) is NOT
    invoked by this agent.  No Buy/Hold/Avoid is produced.
    """
    print(f"[run_general_finance_agent] question={question!r} intent={intent!r}")

    # ── HARDCODED TRACE BYPASS ────────────────────────────────────────────────
    # Temporary: if the question mentions "interest rates", return a known-good
    # response so we can confirm the full pipeline (parse → serialize → frontend)
    # works before blaming the LLM.  Remove once the root cause is confirmed.
    if "interest rate" in question.lower():
        hardcoded = GeneralFinanceAnswer(
            answer=(
                "Higher interest rates tend to pressure tech stocks because future earnings "
                "become less valuable when discounted at higher rates — and tech companies "
                "derive most of their value from profits expected years from now."
            ),
            bullets=[
                "The mechanism: rising rates increase the discount rate used to value future "
                "cash flows. A dollar of profit in year 5 is worth less today at 6% than at "
                "2% — and growth stocks have more of their value tied to distant earnings.",
                "In practice: rate rises often trigger rotation from high-multiple tech into "
                "banks, energy, and value stocks that earn more of their profits now.",
                "Watch the 10-year Treasury yield and Fed forward guidance — markets price "
                "rate expectations weeks before the actual decision.",
            ],
            caveats=[
                "Profitable tech companies with strong current cash flows (Apple, Alphabet) "
                "hold up better than unprofitable high-growth names during rate cycles.",
                "Rate fears can reverse quickly: when the Fed signals a pause, growth stocks "
                "often recover fast, so timing matters.",
            ],
        )
        print(f"[run_general_finance_agent] HARDCODED BYPASS answer={hardcoded.answer[:60]!r}...")
        return hardcoded

    prompt = general_finance_prompt(question, intent=intent)
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
        f"[run_general_finance_agent] LLM RAW GENERAL ANSWER: "
        f"answer={result.answer!r:.120} "
        f"bullets_count={len(result.bullets)} "
        f"caveats_count={len(result.caveats)}"
    )
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

    The agent calls the LLM with an open-ended prompt that answers the
    question directly without forcing a finance frame, but connects back to
    investing context in the bullets where natural.

    Returns a GeneralFinanceAnswer so the same rendering and fallback
    enforcement logic applies as for run_general_finance_agent.
    """
    print(f"[run_general_fallback_agent] question={question!r}")

    prompt = general_fallback_prompt(question)
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