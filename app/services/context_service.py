"""
Context enrichment service.

This module provides a function to enrich a ``GroundingContext`` with
placeholder values when necessary.  The goal is to ensure that
prompts always receive operational context rather than empty lists.
When a user does not supply a grounding context or when certain
fields are missing, the enrichment fills those fields with explicit
default notes.  These placeholders clearly indicate that specific
data is unavailable rather than allowing the model to hallucinate.

The enrichment function does not fetch live data; it simply injects
structured defaults.  If a field is already populated, it is left
unchanged to preserve user input.  This function is light‑weight
enough to run synchronously as part of the request handling.

Usage:

    from .context_service import enrich_grounding_context
    context = enrich_grounding_context(company, user_question, existing_context)
"""

from __future__ import annotations

from typing import Optional, Dict, List

from ..config import settings
# Import the providers module instead of specific functions.  This makes it
# easier to monkeypatch provider functions in tests since the module will
# always be referenced via the namespace.  Individual functions are not
# imported at module level to avoid capturing stale references.
from . import data_providers

from ..schemas import GroundingContext


def enrich_grounding_context(company: str, user_question: Optional[str], context: Optional[GroundingContext]) -> GroundingContext:
    """Return a fully populated grounding context.

    This function ensures that a ``GroundingContext`` always has values for
    key fields.  It copies the provided context (if any) to avoid
    mutation and then fills in missing fields with placeholder values.

    Parameters
    ----------
    company : str
        The company name relevant to the analysis.
    user_question : Optional[str]
        The question asked by the user; used to record the focus of
        the analysis.
    context : Optional[GroundingContext]
        An existing context supplied by the API caller; may be None.

    Returns
    -------
    GroundingContext
        An enriched copy of the input context with defaults filled.
    """
    # Create a shallow copy or new context to avoid modifying the original.  In
    # Pydantic v2 the preferred method is ``model_copy``; fall back to
    # ``copy`` for compatibility with v1.  Deep copy ensures nested lists
    # are duplicated.
    if context is not None:
        if hasattr(context, "model_copy"):
            ctx = context.model_copy(deep=True)  # type: ignore[attr-defined]
        else:
            ctx = context.copy(deep=True)  # type: ignore[no-untyped-call]
    else:
        ctx = GroundingContext(company=company, user_question=user_question)
    # Populate missing top‑level fields
    if ctx.company is None:
        ctx.company = company
    if ctx.user_question is None:
        ctx.user_question = user_question

    # Optionally fetch external data for grounding.  When the caller enables
    # data retrieval via the ``enable_data_retrieval`` setting, the backend
    # will attempt to gather real financial metrics and recent filings from
    # Financial Modeling Prep (FMP) and the SEC EDGAR system.  These calls
    # are wrapped in a try/except so that network failures never propagate.
    if getattr(settings, "enable_data_retrieval", False):
        try:
            # Derive a ticker symbol for lookup; fall back to company name.
            ticker = ctx.ticker or ctx.company
            fmp_metrics: Dict[str, float] = {}
            if ticker:
                fmp_metrics = data_providers.fetch_fmp_financials(ticker, getattr(settings, "fmp_api_key", "")) or {}
                if fmp_metrics:
                    # Merge numeric metrics into the financials dict
                    for k, v in fmp_metrics.items():
                        try:
                            ctx.financials[k] = float(v)
                        except Exception:
                            pass
            # Fetch recent filings and known facts from SEC EDGAR
            sec_data = data_providers.fetch_sec_filings(ctx.company, ctx.ticker, getattr(settings, "sec_user_agent", "")) or {}
            # Append events, facts, and notes if available
            if sec_data:
                events = sec_data.get("recent_events", []) or []
                if events:
                    ctx.recent_events.extend(events)
                facts = sec_data.get("known_facts", []) or []
                if facts:
                    ctx.known_facts.extend(facts)
                notes = sec_data.get("source_notes", []) or []
                if notes:
                    ctx.source_notes.extend(notes)
            # If we obtained financial metrics, add a summary fact and source note
            if fmp_metrics:
                # Compose a brief fact string summarising financial performance
                parts: List[str] = []
                rev = fmp_metrics.get("revenue")
                ni = fmp_metrics.get("net_income")
                ebitda = fmp_metrics.get("ebitda")
                eps = fmp_metrics.get("eps")
                if rev is not None:
                    parts.append(f"revenue of {rev}")
                if ni is not None:
                    parts.append(f"net income of {ni}")
                if ebitda is not None:
                    parts.append(f"EBITDA of {ebitda}")
                if eps is not None:
                    parts.append(f"EPS of {eps}")
                if parts:
                    ctx.known_facts.append(
                        f"According to FMP, the latest financials show {'; '.join(parts)}."
                    )
                # Note the data source
                ctx.source_notes.append("Financial metrics from FMP Income Statement API")
                # Derive a simple macro context narrative from the metrics.  Positive
                # profitability suggests resilience, whereas negative net income
                # signals vulnerability to macroeconomic shocks.  Revenue
                # provides context on the scale of operations.
                try:
                    if ni is not None:
                        ni_float = float(ni)
                        if ni_float > 0:
                            ctx.macro_context.append(
                                f"The company reports positive net income ({ni}), indicating profitability that may help mitigate macroeconomic risks."
                            )
                        elif ni_float < 0:
                            ctx.macro_context.append(
                                f"The company reports negative net income ({ni}), suggesting vulnerability to economic downturns and external shocks."
                            )
                    if rev is not None:
                        ctx.macro_context.append(
                            f"With revenue of {rev}, the company's scale influences its sensitivity to market demand and economic cycles."
                        )
                except Exception:
                    pass
        except Exception:
            # Retrieval failures are silent and do not override placeholders
            pass
    # Enrich lists with explicit placeholder notes when empty
    # If no known facts were provided or retrieved, supply a substantive placeholder
    if not ctx.known_facts:
        ctx.known_facts = [
            f"Key facts about {company} (industry, products, market share) were not provided."
        ]
    # If no recent events were retrieved, provide a descriptive placeholder
    if not ctx.recent_events:
        ctx.recent_events = [f"No recent SEC filings or notable events were found for {company}."]
    # Provide a generic macro context placeholder if none is supplied
    if not ctx.macro_context:
        ctx.macro_context = [
            f"General macroeconomic factors such as inflation and interest rates may influence {company}."
        ]
    # If no source notes were added, supply a note indicating absence of external data
    if not ctx.source_notes:
        ctx.source_notes = ["No external data sources were used."]
    # Leave financials as is; if empty, it remains an empty dict to avoid implying fake data
    return ctx