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

    This is the most output-critical prompt.  It explicitly instructs
    the model to:
    - Name the company in verdict_reasoning
    - Reference top drivers and risks by name and connect them causally
    - Avoid generic hedging phrases
    - Produce analyst-quality, decision-specific language
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
        f"You are the Head Analyst writing an internal investment committee brief for '{company}'.\n"
        "This is an internal decision document for portfolio managers — not external advice.\n"
        "Write with the directness and specificity of a senior hedge fund analyst.\n\n"

        "━━━ AGENT REPORTS ━━━\n"
        f"{agent_reports}\n"
        f"Context:\n{context_section}\n\n"

        "━━━ YOUR TASK ━━━\n"
        f"Synthesize the agent reports into a single investment decision note for '{company}'.\n"
        "Resolve contradictions across agents. Weigh evidence quality. Produce a definitive verdict.\n\n"

        "━━━ FIELD REQUIREMENTS ━━━\n\n"

        "final_verdict (string):\n"
        "  One word only: bullish, constructive, neutral, cautious, or bearish.\n"
        "  Choose the word that best captures the risk/reward balance.\n\n"

        "verdict_reasoning (string):\n"
        "  EXACTLY 4 sentences. This is the most important field — it is read directly by the user.\n"
        "  Write in second person ('you'). Use plain English. No jargon. No institutional hedging.\n"
        "  Imagine you are explaining this to a smart friend who is new to investing.\n\n"
        "  Sentence 1 — Decision + company name (mandatory opening format):\n"
        "    Map final_verdict to an opening action phrase:\n"
        f"      bullish      → 'Add {company}.' or 'Add to {company}.'\n"
        f"      constructive → 'Add {company} on weakness.' or 'Hold and consider adding {company}.'\n"
        f"      neutral      → 'Hold {company} for now.'\n"
        f"      cautious     → 'Be cautious with {company} here.' or 'Hold {company} lightly.'\n"
        f"      bearish      → 'Avoid {company} at current levels.'\n"
        f"    Always use '{company}' by name — never a ticker symbol.\n\n"
        "  Sentences 2–3 — Driver into risk (one causal story, not two separate points):\n"
        "    Sentence 2: explain what is working and why it matters to the business in plain terms.\n"
        "      Reference the top 1-2 drivers from key_drivers_ranked. Paraphrase naturally — do NOT copy bullet text.\n"
        "    Sentence 3: carry the story forward into the risk using 'but' or 'however'.\n"
        "      Reference the top risk from key_risks_ranked. Show how it limits or threatens what sentence 2 described.\n"
        "      The two sentences should read as cause → complication, not as two unrelated observations.\n\n"
        "  Sentence 4 — Guidance (opener blended into action, not prepended as a prefix):\n"
        "    The opener and the action must form one grammatically natural sentence.\n"
        "    The verb after the opener should be gerund or infinitive form — NOT an imperative.\n"
        "      Wrong: 'Given this setup, Add Nvidia.'         ← imperative clashes with the opener\n"
        "      Right: 'Given this setup, adding to Nvidia on weakness makes sense.'\n"
        "      Wrong: 'If you already own it, Hold Apple.'   ← sounds robotic\n"
        "      Right: 'If you already own Apple, holding for now makes sense.'\n\n"
        "    Choose the opener that fits final_verdict — the opener signals the stance:\n"
        f"      bullish      → 'Given this setup, [gerund action]...'              e.g. 'Given this setup, adding on weakness makes sense — watch [X].'\n"
        f"      constructive → 'At this point, [gerund action]...'                 e.g. 'At this point, adding on any pullback makes sense — keep an eye on [X].'\n"
        f"      neutral      → 'If you already own {company}, [gerund action]...'  e.g. 'If you already own {company}, holding makes sense — watch [X] before adding more.'\n"
        f"      cautious     → 'For now, [gerund action] is the safer move...'     e.g. 'For now, holding lightly and avoiding new exposure is the safer move until [X] improves.'\n"
        f"      bearish      → 'At this point, [gerund action]...'                 e.g. 'At this point, avoiding new exposure makes sense — the risk of [X] outweighs the upside.'\n"
        "    Do NOT swap openers across verdicts.\n"
        "    After the opener + action: add one concrete watchpoint from what_to_monitor.\n"
        "    The full sentence should read as natural speech, not a template with a prefix attached.\n\n"
        "  TONE:\n"
        "  ✓ Conversational but professional — like a trusted advisor talking through their thinking\n"
        "  ✓ Fluid and connected — the four sentences should read as one coherent thought, not four bullets\n"
        "  ✓ Active voice throughout — no passive constructions\n"
        "  ✓ Accessible — a newcomer to investing should understand every sentence\n"
        "  ✓ Specific — name actual drivers and risks, not generic observations\n\n"
        "  BANNED phrases (any of these fails the output):\n"
        "  ✗ 'mixed signals'\n"
        "  ✗ 'balanced outlook'\n"
        "  ✗ 'could go either way'\n"
        "  ✗ 'uncertainty remains'\n"
        "  ✗ 'while there are risks'\n"
        "  ✗ 'overall picture is mixed'\n"
        "  ✗ 'no compelling reason'\n"
        "  ✗ 'wait for clearer signals'\n"
        "  ✗ 'stay patient —'\n"
        "  ✗ 'investment committee'\n"
        "  ✗ 'portfolio manager'\n"
        "  ✗ 'risk/reward'\n\n"
        "  EXAMPLES — note how opener and action blend into one fluid sentence:\n\n"
        "  Neutral verdict:\n"
        "  'Hold Apple for now. Services growth continues to support the business and keeps margins\n"
        "   healthy even when hardware sales slow, but the stock's valuation already reflects that\n"
        "   strength, which limits how much upside you're likely to see near term. If you already own\n"
        "   Apple, holding makes sense — just keep an eye on the next earnings call for any sign that\n"
        "   Services momentum is fading before adding more.'\n\n"
        "  Bullish verdict:\n"
        "  'Add Nvidia. Data-center demand for its GPU platform continues to outpace supply, and the\n"
        "   software moat around CUDA makes it difficult for customers to switch, but any pause in\n"
        "   hyperscaler capex spending could slow order flow faster than the market expects. Given this\n"
        "   setup, adding on any near-term pullback makes sense — watch quarterly data-center revenue\n"
        "   guidance for confirmation that demand remains intact.'\n\n"
        "  Cautious verdict:\n"
        "  'Be cautious with Tesla here. Strong brand recognition and its energy-storage business\n"
        "   provide real long-term optionality, but deteriorating vehicle margins and intensifying\n"
        "   EV competition are pressuring profitability right now. For now, holding lightly and avoiding\n"
        "   new exposure is the safer move — gross margins need to stabilise above 18% for at least\n"
        "   two quarters before the thesis improves.'\n\n"

        "key_drivers_ranked (list, 3-5 items):\n"
        "  Ordered most important first.\n"
        f"  Each item: one specific sentence starting with a named signal for '{company}'.\n"
        "  Example format: 'Services revenue growing >15% annually provides durable recurring income and margin uplift.'\n"
        "  NOT: 'The company has strong revenue growth.'\n\n"

        "key_risks_ranked (list, 3-5 items):\n"
        "  Ordered most severe first.\n"
        f"  Each item: one specific sentence naming the risk mechanism for '{company}'.\n"
        "  Example format: 'Hardware margin compression from commoditizing ASICs threatens blended gross margin trajectory.'\n"
        "  NOT: 'There are risks to margins.'\n\n"

        "what_to_monitor (list, 3-5 items):\n"
        "  Specific metrics or events with thresholds or timeframes where possible.\n"
        "  Example: 'Gross margin trajectory over the next 2 reporting periods — deterioration below 43% would pressure the thesis.'\n"
        "  NOT: 'Watch for changes in the business environment.'\n\n"

        "what_changes_the_thesis (list, 3-5 items):\n"
        "  Specific observable events that would flip the verdict.\n"
        "  Example: 'If services revenue growth decelerates below 10% for two consecutive quarters, the premium valuation becomes indefensible.'\n"
        "  NOT: 'If conditions worsen significantly.'\n\n"

        "confidence_score (float 0.0–1.0):\n"
        "  ≥0.70 requires strong, consistent evidence across agents.\n"
        "  0.50–0.69 for moderate evidence with some contradictions.\n"
        "  <0.50 if data is thin, contradictory, or thesis is highly fragile.\n\n"

        "confidence_level (string): 'high', 'medium', or 'low'\n\n"

        "thesis_fragility (string):\n"
        "  1-2 sentences. Name the single biggest assumption the thesis depends on and what breaks if it fails.\n\n"

        "Also include: bull_case (list), bear_case (list), key_risks (list), key_catalysts (list),\n"
        "macro_overlay (list), what_changes_the_thesis (list), assumptions (list), uncertainties (list).\n\n"

        "━━━ OUTPUT ORDER — CRITICAL ━━━\n"
        "Output the JSON fields in EXACTLY this order so the most important fields are never truncated:\n"
        "  1. final_verdict        ← FIRST\n"
        "  2. verdict_reasoning    ← SECOND (REQUIRED — never omit, never leave empty)\n"
        "  3. confidence_score\n"
        "  4. confidence_level\n"
        "  5. thesis_fragility\n"
        "  6. key_drivers_ranked\n"
        "  7. key_risks_ranked\n"
        "  8. what_to_monitor\n"
        "  9. what_changes_the_thesis\n"
        " 10. bull_case, bear_case, key_risks, key_catalysts, macro_overlay\n"
        " 11. assumptions, uncertainties, and all remaining fields\n\n"
        "verdict_reasoning MUST be a non-empty string. If you are uncertain, write your best assessment.\n"
        "An empty verdict_reasoning is not acceptable.\n\n"
        "Return only the JSON object without surrounding text."
    )