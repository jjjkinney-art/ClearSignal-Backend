"""
Prompt templates for the AI analyst agents.

Each function returns a formatted prompt instructing the language model
to produce structured JSON output aligned with the new schemas.  The
prompts require bullet‑style lists, clear separation of known facts
from inferred reasoning, explicit treatment of assumptions and
uncertainties, and ranking of key drivers and risks in the synthesizer.
The optional ``GroundingContext`` is injected into the prompt so that
the model can base its reasoning on supplied data rather than fabricating
details.
"""

from __future__ import annotations

from typing import Optional
import json

from .schemas import GroundingContext


def _context_section(context: Optional[GroundingContext]) -> str:
    """Format the grounding context as a bullet list for the prompt."""
    if not context:
        return ""
    lines = []
    if context.known_facts:
        lines.append("Known facts:")
        for fact in context.known_facts:
            lines.append(f"- {fact}")
    if context.financials:
        lines.append("Financials:")
        for k, v in context.financials.items():
            lines.append(f"- {k}: {v}")
    if context.recent_events:
        lines.append("Recent events:")
        for ev in context.recent_events:
            lines.append(f"- {ev}")
    if context.macro_context:
        lines.append("Macro context:")
        for mc in context.macro_context:
            lines.append(f"- {mc}")
    if context.source_notes:
        lines.append("Source notes:")
        for sn in context.source_notes:
            lines.append(f"- {sn}")
    return "\n".join(lines)


def equity_prompt(company: str, context: Optional[GroundingContext] = None, user_question: Optional[str] = None) -> str:
    """Construct a prompt for the Equity Analyst.

    The model is instructed to produce JSON with list fields.  It must
    clearly distinguish supplied facts (provided via ``context``) from
    inferred reasoning.  It should avoid inventing precise numbers
    beyond what is supplied.
    """
    context_section = _context_section(context)
    question_section = f"\nFocus question: {user_question}" if user_question else ""
    return (
        f"You are a disciplined Equity Analyst at a top-tier investment firm. "
        f"Analyse the company '{company}'.{question_section} Provide your analysis as JSON with the following keys: "
        "business_overview (list of bullet points), bull_case (list), bear_case (list), key_risks (list), key_catalysts (list), "
        "assumptions (list), uncertainties (list).\n"
        "Use the supplied context below to ground your analysis. Clearly indicate which items come from known facts (supplied) and which are inferred assumptions. "
        "Use bullet points for all list fields and avoid paragraphs. Do not fabricate precise numbers or facts that are not present in the context.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object without any surrounding text."
    )


def macro_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Macro Analyst."""
    context_section = _context_section(context)
    return (
        f"You are a Macro Analyst at a professional investment firm analysing the macroeconomic environment for '{company}'. "
        "Produce a JSON object with keys: macro_overlay (list of bullet points), assumptions (list), uncertainties (list). "
        "Consider interest rates, inflation, economic cycles, sector trends, and geopolitics. Link each macro factor to potential impacts on the company. "
        "Use the context provided and avoid inventing facts not supplied.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )


def opportunity_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Opportunity Scanner."""
    context_section = _context_section(context)
    return (
        f"You are an Opportunity Scanner Agent. Identify asymmetric opportunities, emerging themes, and catalysts for '{company}'. "
        "Return a JSON object with keys: opportunity_summary (list), assumptions (list), uncertainties (list). "
        "Explain why each opportunity is asymmetric and what could unlock value. Base your reasoning on supplied facts.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )


def research_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Research Synthesizer."""
    context_section = _context_section(context)
    return (
        f"You are a Research Synthesizer Agent. Summarize external research findings for '{company}'. "
        "Return a JSON object with keys: research_summary (list), assumptions (list), uncertainties (list). "
        "Use bullet points to highlight key insights, disagreements, and new data. If no material research is found, return an empty list.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )


def education_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Education/Explanation agent."""
    context_section = _context_section(context)
    return (
        f"You are an Education and Explanation Agent. Explain the analysis of '{company}' for a non-expert audience. "
        "Return a JSON object with keys: education_summary (list), assumptions (list), uncertainties (list). "
        "Use bullet points and simple language without losing rigour. Clarify reasoning behind bull and bear cases, macro impacts, and key drivers.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )


def accounting_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Accounting/Operations agent."""
    context_section = _context_section(context)
    return (
        f"You are an Accounting and Operations Analyst. Analyse the financial statements and operational performance of '{company}'. "
        "Return a JSON object with keys: accounting_summary (list), assumptions (list), uncertainties (list). "
        "Identify key metrics, anomalies, trends, and operational drivers. Explain implications of accounting choices.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )


def synthesizer_prompt(
    company: str,
    equity: dict,
    macro: dict,
    opportunity: dict,
    research: dict,
    education: dict,
    accounting: dict,
    context: Optional[GroundingContext] = None,
) -> str:
    """Construct a prompt for the Head Analyst synthesizer.

    The synthesizer receives the outputs from all agents as JSON and must
    reconcile them into a unified structured summary.  It is asked to
    rank key drivers and risks, state what would change the thesis,
    assign a confidence score, provide reasoning, and assess thesis
    fragility.  All list fields should be ordered by importance.
    """
    context_section = _context_section(context)
    return (
        "You are the Head Analyst at a top-tier investment firm. Your job is to synthesize inputs from specialist agents and produce a unified investment thesis. "
        "You will be given JSON outputs from the Equity Analyst, Macro Analyst, Opportunity Scanner, Research Synthesizer, Education Agent, and Accounting Analyst. "
        "Combine these into a single JSON object with the following keys: "
        "business_overview (list), bull_case (list), bear_case (list), key_risks (list), key_catalysts (list), macro_overlay (list), "
        "opportunity_summary (list), research_summary (list), education_summary (list), accounting_summary (list), "
        "key_drivers_ranked (list), key_risks_ranked (list), what_to_monitor (list), what_changes_the_thesis (list), "
        "final_verdict (string: bullish|bearish|neutral|mixed), verdict_reasoning (string), confidence_score (float between 0 and 1), "
        "confidence_reasoning (string), thesis_fragility (string), assumptions (list), uncertainties (list).\n"
        "You must resolve contradictions, weigh evidence, and rank the most important drivers and risks. Clearly separate facts from assumptions. "
        "Your confidence score should reflect the strength of the evidence and the fragility of the thesis. If the underlying data is thin or contradictory, assign a lower confidence.\n"
        f"\nEquityAnalysis: {json.dumps(equity, ensure_ascii=False)}\n"
        f"MacroAnalysis: {json.dumps(macro, ensure_ascii=False)}\n"
        f"OpportunityAnalysis: {json.dumps(opportunity, ensure_ascii=False)}\n"
        f"ResearchAnalysis: {json.dumps(research, ensure_ascii=False)}\n"
        f"EducationAnalysis: {json.dumps(education, ensure_ascii=False)}\n"
        f"AccountingAnalysis: {json.dumps(accounting, ensure_ascii=False)}\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object."
    )