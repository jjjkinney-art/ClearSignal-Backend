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