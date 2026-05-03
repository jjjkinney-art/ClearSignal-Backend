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

    Forces company-specific reasoning — each bullet must name a signal,
    segment, or mechanism specific to this company, not a generic observation.
    """
    context_section = _context_section(context)
    question_section = f"\nFocus question: {user_question}" if user_question else ""
    return (
        f"You are a Senior Equity Analyst who has followed '{company}' closely for years.{question_section}\n\n"
        f"Analyse '{company}' with the specificity of someone who knows its business model deeply. "
        "Every bullet must contain a specific, verifiable claim tied to this company — not a generic observation that could apply to any company.\n\n"
        "Requirements:\n"
        f"- Name '{company}' or its specific segments/products in each bullet\n"
        "- Identify the company's primary revenue drivers and their growth trajectories\n"
        "- Assess the margin profile: gross margins, operating margins, and their direction\n"
        "- Name specific competitive threats or moat characteristics\n"
        "- Reference valuation context if relevant (premium/discount vs. peers or history)\n"
        "- Do not fabricate specific numbers not in the supplied context, but do describe known directional trends\n\n"
        "Return JSON with keys:\n"
        "- business_overview (list, 3-5 bullets): core business model, key revenue streams, competitive position\n"
        "- bull_case (list, 3-5 bullets): specific bullish arguments tied to this company's dynamics\n"
        "- bear_case (list, 3-5 bullets): specific bearish arguments naming the risk mechanism\n"
        "- key_risks (list, 3-5 bullets): risks ranked by severity, each naming what breaks and how\n"
        "- key_catalysts (list, 3-5 bullets): near-term catalysts with specific expected impact on the company\n"
        "- assumptions (list): key assumptions your analysis relies on\n"
        "- uncertainties (list): specific unknowns that could materially change the view\n\n"
        "Use the context below. Clearly separate context-supplied facts from inferred analysis.\n"
        f"\nContext:\n{context_section}\n"
        "Return only the JSON object without any surrounding text."
    )


def macro_prompt(company: str, context: Optional[GroundingContext] = None) -> str:
    """Construct a prompt for the Macro Analyst.

    Forces direct linkage of macro conditions to company-specific impacts —
    not generic macro commentary.
    """
    context_section = _context_section(context)
    return (
        f"You are a Macro Strategist assessing how macroeconomic conditions directly affect '{company}'.\n\n"
        "For each macro factor you identify, you must state:\n"
        "1. The specific condition (e.g. rising real rates, dollar strengthening, consumer spending slowdown)\n"
        f"2. The direction of impact on '{company}' (positive / negative / mixed)\n"
        "3. The mechanism — how it flows through to revenue, margins, demand, or valuation specifically for this company\n\n"
        "Do NOT write generic macro observations. Every bullet must connect the macro condition to "
        f"'{company}'\\'s specific business model.\n\n"
        "Return JSON with keys:\n"
        f"- macro_overlay (list, 3-5 bullets): each in format '[macro condition] → [direct effect on {company}\\'s [metric/business]]'\n"
        "- assumptions (list): macro assumptions underlying the analysis\n"
        "- uncertainties (list): macro variables that could shift the outlook materially\n\n"
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

    Structured so that the two highest-priority fields — final_verdict and
    verdict_reasoning — are demanded before any list fields, making it
    impossible for token budget pressure to starve them.  A hard in-prompt
    fallback string is provided so the model always has something concrete
    to write even under uncertainty.
    """
    context_section = _context_section(context)

    # Aggregate agent reports (omit education to save tokens — it adds noise)
    agent_reports = (
        f"EQUITY ANALYSIS:\n{json.dumps(equity, ensure_ascii=False)}\n\n"
        f"MACRO ANALYSIS:\n{json.dumps(macro, ensure_ascii=False)}\n\n"
        f"OPPORTUNITY ANALYSIS:\n{json.dumps(opportunity, ensure_ascii=False)}\n\n"
        f"ACCOUNTING ANALYSIS:\n{json.dumps(accounting, ensure_ascii=False)}\n\n"
        f"RESEARCH SUMMARY:\n{json.dumps(research, ensure_ascii=False)}\n"
    )

    return (
        f"You are the Head Analyst writing an investment decision note for '{company}'.\n"
        "Write with the directness of a senior analyst. Plain English. Second person.\n\n"

        "━━━ AGENT REPORTS ━━━\n"
        f"{agent_reports}\n"
        f"Context:\n{context_section}\n\n"

        "━━━ YOUR TASK ━━━\n"
        f"Synthesize the agent reports into a single investment decision note for '{company}'.\n"
        "Resolve contradictions. Weigh evidence quality. Produce a definitive verdict.\n\n"

        # ── CRITICAL BLOCK — must come before ALL list fields in the output ──
        "━━━ MANDATORY: OUTPUT THESE TWO FIELDS FIRST — NO EXCEPTIONS ━━━\n\n"

        "YOU MUST write both fields below before writing any lists.\n"
        "An empty verdict_reasoning is a system failure. It is NOT acceptable under any circumstances.\n"
        "If you are uncertain, still produce a best-effort explanation — use the hard fallback below.\n\n"

        '{"final_verdict": "...", "verdict_reasoning": "..."}\n\n'

        "▶ final_verdict (string) — write this first:\n"
        "  One word only: bullish, constructive, neutral, cautious, or bearish.\n\n"

        "▶ verdict_reasoning (string) — write this second, IMMEDIATELY after final_verdict:\n"
        "  YOU MUST produce a non-empty string here. This field CANNOT be empty or null.\n\n"
        "  HARD FALLBACK — if you cannot write the full explanation below, output EXACTLY this\n"
        "  (substituting the real verdict word and company name):\n"
        f'  "Hold {company} for now. The current signals are not strong enough to justify '
        f'adding exposure, but the business remains stable. Monitor the key drivers and risks '
        f'listed below before making a decision."\n\n'
        "  Otherwise, write EXACTLY 4 sentences in this structure:\n\n"
        "  Sentence 1 — Decision + company name:\n"
        "    Map final_verdict to an opening action phrase:\n"
        f"      bullish      → 'Add {company}.' or 'Add to {company}.'\n"
        f"      constructive → 'Add {company} on weakness.' or 'Hold and consider adding {company}.'\n"
        f"      neutral      → 'Hold {company} for now.'\n"
        f"      cautious     → 'Be cautious with {company} here.' or 'Hold {company} lightly.'\n"
        f"      bearish      → 'Avoid {company} at current levels.'\n"
        f"    Always use '{company}' by name — never a ticker symbol.\n\n"
        "  Sentence 2 — What is working (plain English, company-specific):\n"
        "    Explain the top driver from key_drivers_ranked in one sentence. Paraphrase naturally.\n\n"
        "  Sentence 3 — The complication (use 'but' or 'however'):\n"
        "    Carry Sentence 2 forward into the top risk. Show cause → complication.\n\n"
        "  Sentence 4 — Guidance (opener + gerund action, one natural sentence):\n"
        f"      bullish      → 'Given this setup, adding on weakness makes sense — watch [X].'\n"
        f"      constructive → 'At this point, adding on any pullback makes sense — keep an eye on [X].'\n"
        f"      neutral      → 'If you already own {company}, holding makes sense — watch [X] before adding more.'\n"
        f"      cautious     → 'For now, holding lightly and avoiding new exposure is the safer move until [X] improves.'\n"
        f"      bearish      → 'At this point, avoiding new exposure makes sense — the risk of [X] outweighs the upside.'\n\n"
        "  TONE: Conversational, active voice, accessible, specific — no jargon, no hedging.\n"
        "  BANNED: 'mixed signals', 'balanced outlook', 'could go either way', 'uncertainty remains',\n"
        "          'while there are risks', 'no compelling reason', 'wait for clearer signals',\n"
        "          'stay patient', 'risk/reward'\n\n"
        "  EXAMPLES:\n"
        "  Neutral: 'Hold Apple for now. Services growth keeps margins healthy even when hardware\n"
        "   sales slow, but the stock's valuation already reflects that strength, limiting near-term\n"
        "   upside. If you already own Apple, holding makes sense — watch the next earnings call\n"
        "   for any sign that Services momentum is fading before adding more.'\n\n"
        "  Bullish: 'Add Nvidia. Data-center demand for its GPU platform outpaces supply and the\n"
        "   CUDA software moat makes switching difficult, but any pause in hyperscaler capex could\n"
        "   slow order flow faster than the market expects. Given this setup, adding on any\n"
        "   near-term pullback makes sense — watch quarterly data-center revenue guidance.'\n\n"
        "  Cautious: 'Be cautious with Tesla here. Brand recognition and energy storage provide\n"
        "   real long-term optionality, but deteriorating vehicle margins and intensifying EV\n"
        "   competition are pressuring profitability right now. For now, holding lightly and\n"
        "   avoiding new exposure is the safer move — gross margins need to stabilise above 18%\n"
        "   for two quarters before the thesis improves.'\n\n"

        # ── Remaining fields — listed AFTER the critical block ────────────────
        "━━━ REMAINING FIELDS (write after verdict_reasoning) ━━━\n\n"

        "confidence_score (float 0.0–1.0):\n"
        "  ≥0.70 strong consistent evidence. 0.50–0.69 moderate with some contradictions. <0.50 thin or contradictory.\n\n"

        "confidence_level (string): 'high', 'medium', or 'low'\n\n"

        "thesis_fragility (string): 1-2 sentences — the single biggest assumption and what breaks if it fails.\n\n"

        "key_drivers_ranked (list, exactly 3 items, most important first):\n"
        f"  Each: one specific sentence naming a signal for '{company}'.\n"
        "  Good: 'Services revenue growing >15% annually provides durable recurring income and margin uplift.'\n"
        "  Bad:  'The company has strong revenue growth.'\n\n"

        "key_risks_ranked (list, exactly 3 items, most severe first):\n"
        f"  Each: one specific sentence naming the risk mechanism for '{company}'.\n"
        "  Good: 'Hardware margin compression from commoditizing ASICs threatens blended gross margin trajectory.'\n"
        "  Bad:  'There are risks to margins.'\n\n"

        "what_to_monitor (list, 3 items): specific metrics or events with thresholds or timeframes.\n\n"

        "what_changes_the_thesis (list, 3 items): specific observable events that would flip the verdict.\n\n"

        "Also include: bull_case (list, 3 items), bear_case (list, 3 items), key_risks (list, 3 items),\n"
        "key_catalysts (list, 3 items), macro_overlay (list, 3 items), assumptions (list), uncertainties (list).\n\n"

        "━━━ JSON OUTPUT ORDER — STRICTLY REQUIRED ━━━\n"
        "Write the JSON fields in EXACTLY this order:\n"
        "  1. final_verdict\n"
        "  2. verdict_reasoning   ← MUST BE NON-EMPTY\n"
        "  3. confidence_score\n"
        "  4. confidence_level\n"
        "  5. thesis_fragility\n"
        "  6. key_drivers_ranked\n"
        "  7. key_risks_ranked\n"
        "  8. what_to_monitor\n"
        "  9. what_changes_the_thesis\n"
        " 10. bull_case, bear_case, key_risks, key_catalysts, macro_overlay\n"
        " 11. assumptions, uncertainties, remaining fields\n\n"
        "Return only the JSON object. No prose before or after it."
    )