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

from typing import List, Optional
import json

from .schemas import GroundingContext, RetrievedEvidence


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


def _format_evidence_section(evidence: Optional[List[RetrievedEvidence]]) -> str:
    """Render retrieved evidence as a prompt section.

    Returns an empty string when evidence is None or empty so that callers
    can unconditionally concatenate the result — no if-guards needed at the
    call site.

    Evidence items are sorted by relevance_score descending before rendering
    so the most relevant item always appears first regardless of retrieval order.
    """
    if not evidence:
        return ""

    sorted_ev = sorted(evidence, key=lambda e: e.relevance_score, reverse=True)

    lines: List[str] = [
        "\n━━━ CURRENT CONTEXT ━━━",
        "The following evidence was retrieved for this question.",
        "Rules for using it:",
        "  - Prioritize this evidence over generic abstractions or training memory.",
        "  - Explain WHY each piece matters — don't just restate it.",
        "  - Synthesize it into causal reasoning: what happened, why, and what it means.",
        "  - If the evidence is thin or dated, note the limitation in caveats.",
        "",
    ]
    for i, ev in enumerate(sorted_ev, 1):
        lines.append(f"[{i}] {ev.title}")
        lines.append(
            f"    Source: {ev.source} | Date: {ev.timestamp} | "
            f"Relevance: {ev.relevance_score:.2f}"
        )
        lines.append(f"    {ev.summary}")
        lines.append("")

    lines.append("Use this context to make the answer specific and current.")
    return "\n".join(lines) + "\n"


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
        f'  "Hold {company} for now. Right now, the signals aren\'t strong enough to justify '
        f'adding exposure, but the business remains stable. It\'s worth monitoring the key '
        f'drivers and risks before making a move."\n\n'
        "  Otherwise, write EXACTLY 4 sentences in this structure:\n\n"
        "  Sentence 1 — Decision + company name (ONLY sentence that uses the company name):\n"
        "    Map final_verdict to an opening action phrase:\n"
        f"      bullish      → 'Add {company}.' or 'Add to {company}.'\n"
        f"      constructive → 'Add {company} on weakness.' or 'Hold and consider adding {company}.'\n"
        f"      neutral      → 'Hold {company} for now.'\n"
        f"      cautious     → 'Be cautious with {company} here.' or 'Hold {company} lightly.'\n"
        f"      bearish      → 'Avoid {company} at current levels.'\n"
        f"    Always use '{company}' by name in Sentence 1. Never use a ticker symbol.\n\n"
        "  Sentence 2 — What is working (plain English, driver-led):\n"
        "    Explain the top driver from key_drivers_ranked in one sentence. Paraphrase naturally.\n"
        "    Don't start with 'The company' or 'The current evidence for [name]'.\n"
        "    Instead, lead with the signal itself: 'Services growth...', 'Data-center demand...'\n"
        "    Use 'the stock', 'it', or 'the company' if you need a pronoun — not the company name.\n\n"
        "  Sentence 3 — The complication (connect with 'but' or 'however'):\n"
        "    Carry Sentence 2 forward into the top risk. One causal flow: working → but risk.\n"
        "    Use contractions naturally: doesn't, isn't, that's, it's.\n\n"
        "  Sentence 4 — Guidance (opener + gerund action, one natural sentence):\n"
        f"      bullish      → 'Given this setup, adding on weakness makes sense — watch [X].'\n"
        f"      constructive → 'At this point, adding on any pullback makes sense — keep an eye on [X].'\n"
        f"      neutral      → 'If you already own it, holding makes sense — watch [X] before adding more.'\n"
        f"      cautious     → 'For now, holding lightly is the safer move — don't add until [X] improves.'\n"
        f"      bearish      → 'At this point, staying out makes sense — the risk of [X] outweighs the upside.'\n\n"
        "  TONE RULES:\n"
        "  - Name the company only in Sentence 1. Use 'the stock', 'it', 'the company' after that.\n"
        "  - Use contractions where natural: doesn't, don't, it's, that's, there's, isn't.\n"
        "  - Sentences 2→3 should feel like one continuous thought, not two separate observations.\n"
        "  - Avoid rigid openers like 'The current evidence for X does not yet...' — write naturally.\n"
        "  - Active voice. No jargon. Decisive but not overconfident.\n"
        "  BANNED: 'mixed signals', 'balanced outlook', 'could go either way', 'uncertainty remains',\n"
        "          'while there are risks', 'no compelling reason', 'wait for clearer signals',\n"
        "          'stay patient', 'risk/reward'\n\n"
        "  EXAMPLES — note how only Sentence 1 uses the company name:\n\n"
        "  Neutral: 'Hold Apple for now. Services growth keeps margins healthy even when hardware\n"
        "   sales slow, but the stock's valuation already reflects that strength — which limits\n"
        "   how much upside you're likely to see from here. If you already own it, holding makes\n"
        "   sense — just watch the next earnings call for any sign that Services momentum is\n"
        "   fading before adding more.'\n\n"
        "  Bullish: 'Add Nvidia. Data-center demand for its GPU platform continues to outpace\n"
        "   supply, and the CUDA software moat makes it hard for customers to switch — but any\n"
        "   pause in hyperscaler capex spending could slow order flow faster than the market\n"
        "   expects. Given this setup, adding on any near-term pullback makes sense — watch\n"
        "   quarterly data-center revenue guidance to confirm demand stays intact.'\n\n"
        "  Cautious: 'Be cautious with Tesla here. Brand recognition and the energy storage\n"
        "   business provide real long-term optionality, but deteriorating vehicle margins and\n"
        "   intensifying EV competition are pressuring profitability right now. For now, holding\n"
        "   lightly is the safer move — gross margins need to stabilise above 18% for two\n"
        "   quarters before it's worth adding more.'\n\n"

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


# ── General finance Q&A prompt ────────────────────────────────────────────────

# Intent → persona / instruction block
_INTENT_BLOCKS: dict = {
    "market_question": (
        "You are answering a macro or market question.\n"
        "Explain the MECHANISM — how the named forces (rates, inflation, Fed policy, etc.) "
        "flow through to the market, asset class, or sector the user asked about.\n"
        "Use plain cause-and-effect language a smart non-expert can follow.\n"
        "Example of a good mechanism sentence: 'Higher rates make future earnings worth less "
        "today, so investors pay lower multiples for growth stocks — and that's why rate "
        "increases tend to hit tech harder than banks.'\n"
        "Do NOT pretend to know current market levels or today's prices unless provided in context.\n"
        "Do NOT give a Buy/Hold/Avoid recommendation unless the user explicitly asked about "
        "a specific stock."
    ),
    "investing_education": (
        "You are answering an investing education question.\n"
        "First define the concept in one crisp sentence anyone can understand.\n"
        "Then explain how investors actually USE it — what decisions does it inform, "
        "what does a high or low value tell you, when does it matter most?\n"
        "Use a concrete example where helpful (e.g. 'A P/E of 30 means you're paying $30 "
        "for every $1 of earnings — that's a growth-stock premium.').\n"
        "Avoid jargon. If you must use a technical term, explain it immediately."
    ),
    "portfolio_question": (
        "You are answering a portfolio-level question.\n"
        "If specific portfolio holdings or context are provided, reference them directly.\n"
        "If no holdings are provided, explain what information would actually matter for "
        "answering the question well (e.g. time horizon, concentration, asset mix).\n"
        "Focus on principles and framework — not a specific trade recommendation.\n"
        "Be honest if the question requires personal financial advice that you cannot give."
    ),
}

_DEFAULT_INTENT_BLOCK = (
    "You are answering a general finance question.\n"
    "Explain the key concept or mechanism clearly and concisely.\n"
    "Focus on how things work, not on predicting specific outcomes."
)


def general_finance_prompt(
    question: str,
    intent: Optional[str] = None,
    evidence: Optional[List[RetrievedEvidence]] = None,
) -> str:
    """Construct a prompt for the general finance Q&A agent.

    This prompt is used for non-company queries: market questions, investing
    education, and portfolio questions.  It produces a structured JSON response
    with a direct answer, elaboration bullets, and honest caveats.

    The prompt is intent-aware so each category gets appropriate framing
    without changing the output schema.

    Parameters
    ----------
    question : str   The user's question.
    intent   : str   Optional intent hint for framing (market_question, etc.).
    evidence : list  Optional retrieved evidence from retrieve_general_finance_evidence().
                     When provided, a "Current Context" section is injected into
                     the prompt so the model can produce current-aware answers.
                     When None or empty, the prompt falls back to conceptual reasoning.
    """
    intent_block = _INTENT_BLOCKS.get(intent or "", _DEFAULT_INTENT_BLOCK)

    # Build a question-specific hard fallback the model can copy verbatim if stuck.
    # This is intentionally generic so it's always accurate regardless of question.
    hard_fallback = (
        f'If you are uncertain how to answer "{question}", write EXACTLY this as the '
        f'"answer" field (substituting actual content for the bracketed parts):\n'
        f'"This question touches on [core financial concept]. In general, [one sentence '
        f'explaining the principle]. [One sentence on what drives the outcome or what to watch]."\n'
        f'That is still a complete, useful answer. An empty answer is never acceptable.'
    )

    return (
        "You are a senior financial analyst explaining finance to a smart, curious person "
        "who is not a professional investor.\n\n"

        "━━━ CRITICAL REQUIREMENT — READ FIRST ━━━\n"
        "The 'answer' field MUST contain at least 2 full sentences. "
        "An empty string, a single word, or a single short sentence is a system failure.\n"
        "You MUST produce a non-empty answer even if:\n"
        "  - You are uncertain about the exact answer\n"
        "  - You lack real-time data\n"
        "  - The question is broad or complex\n"
        "In those cases, explain the general principle or mechanism — that is always possible "
        "and always useful. Never leave 'answer' blank.\n\n"
        f"{hard_fallback}\n\n"

        "Your tone:\n"
        "- Conversational but financially serious\n"
        "- Direct — lead with the answer, not with caveats\n"
        "- Beginner-friendly — no jargon without explanation\n"
        "- Honest about uncertainty — do not pretend to know real-time facts\n\n"

        f"{intent_block}\n\n"

        "━━━ ANSWER STRUCTURE ━━━\n"
        "Produce exactly 3 fields in the JSON output:\n\n"

        "1. 'answer' (string — REQUIRED, minimum 2 sentences)\n"
        "   Answer the question directly. Lead with the conclusion.\n"
        "   Do NOT start with 'It depends', 'Great question', or 'As an AI'.\n"
        "   If uncertain, explain the general principle — do not leave this blank.\n\n"

        "2. 'bullets' (array of exactly 3 strings — REQUIRED)\n"
        "   Bullet 1 — The mechanism or core concept: explain HOW or WHY\n"
        "   Bullet 2 — What this means in practice: a concrete implication or example\n"
        "   Bullet 3 — Practical takeaway: what an investor should think about or watch\n\n"

        "3. 'caveats' (array of exactly 2 strings — REQUIRED)\n"
        "   Caveat 1 — What could change this view, or when the general rule breaks down\n"
        "   Caveat 2 — What to watch (a specific indicator, event, or data point)\n\n"

        "━━━ TONE RULES ━━━\n"
        "BANNED OPENERS — never start the answer with any of these:\n"
        "  'This is a macro question...' / 'This is a market question...'\n"
        "  'This topic involves...' / 'Financial markets respond to...'\n"
        "  '[X] is an important concept...' / '[X] is a key concept...'\n"
        "  'Great question' / 'It depends' / 'As an AI' / 'I recommend'\n\n"
        "BANNED PHRASES — never use in any bullet:\n"
        "  'market participants' / 'related indicators' / 'this factor'\n"
        "  'helps investors understand' / 'understanding the mechanism'\n"
        "  'Watch for changes in related indicators'\n\n"
        "- The first sentence must state the answer or the mechanism directly\n"
        "- Use causal reasoning: explain WHY something happens, not just that it does\n"
        "- Prefer concrete financial nouns: Treasury yields, borrowing costs, discount "
        "  rates, valuation multiples, margin calls, earnings expectations, credit spreads\n"
        "- Use contractions naturally: it's, doesn't, isn't, that's\n"
        "- If real-time data would be needed, note it briefly in caveats — not the answer\n"
        "- Do not give personalised financial advice or specific buy/sell recommendations\n\n"

        "━━━ OUTPUT FORMAT ━━━\n"
        "Return ONLY a JSON object with exactly these three keys:\n"
        '{"answer": "...", "bullets": ["...", "...", "..."], "caveats": ["...", "..."]}\n\n'

        "━━━ EXAMPLES ━━━\n\n"

        "Question: 'How do bond yields affect the stock market?'\n"
        "{\n"
        '  "answer": "Bond yields affect the stock market because they change the return '
        "investors can earn from safer assets. When yields rise, stocks often face pressure "
        "because bonds become more attractive and future corporate profits are discounted at "
        'a higher rate.",\n'
        '  "bullets": [\n'
        '    "Higher yields can reduce stock valuations, especially for growth stocks whose '
        "value is tied to earnings expected years from now — a higher discount rate shrinks "
        'that present value.",\n'
        '    "Rising yields can pull money away from equities into bonds, as investors seek '
        'the better risk-adjusted return from a lower-risk asset.",\n'
        '    "Falling yields can support stocks if they reflect lower inflation — but falling '
        'yields driven by recession fears are a different story and can hurt stocks too."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "If yields fall because recession risk is rising, stocks may still decline — the '
        'reason behind the yield move matters as much as the direction.",\n'
        '    "Watch the 10-year Treasury yield and the spread between short- and long-term '
        "rates — an inverted yield curve (short rates above long rates) has historically "
        'preceded recessions."\n'
        '  ]\n'
        "}\n\n"

        "Question: 'How often does the Fed meet?'\n"
        "{\n"
        '  "answer": "The Federal Reserve\'s FOMC meets eight times per year on a fixed '
        "schedule — roughly every six to eight weeks. Each meeting ends with a policy "
        'statement on interest rates and, at every other meeting, updated economic projections.",\n'
        '  "bullets": [\n'
        '    "Each meeting runs two days and ends with a rate decision: raise, cut, or hold. '
        "The key output isn't just the decision — the language in the statement and the "
        'chair\'s press conference often move markets more than the rate itself.",\n'
        '    "Markets price in expected rate decisions weeks in advance using tools like the '
        "CME FedWatch tool, which shows the probability of a rate change implied by fed "
        'funds futures.",\n'
        '    "The four most watched meetings are typically March, June, September, and '
        "December — they include the updated dot plot, which shows where FOMC members expect "
        'rates to go over the next few years."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "Emergency unscheduled meetings can happen in a crisis — the Fed cut rates '
        'between scheduled meetings in March 2020 in response to the pandemic.",\n'
        '    "The meeting schedule is published at federalreserve.gov; mark the dates because '
        'the days surrounding FOMC meetings are historically among the highest-volatility '
        'days for equities."\n'
        '  ]\n'
        "}\n\n"

        "Question: 'Why do markets crash?'\n"
        "{\n"
        '  "answer": "Markets crash when widespread selling overwhelms buying — usually '
        "triggered by a shock that forces investors to reprice risk all at once. The mechanism "
        "is often self-reinforcing: falling prices trigger margin calls and stop-losses, which "
        'force more selling, which pushes prices down further.",\n'
        '  "bullets": [\n'
        '    "The trigger is typically a repricing of risk: investors realise that their '
        "assumptions about earnings, growth, or stability were too optimistic. Once that "
        'confidence breaks, exits accelerate.",\n'
        '    "Liquidity dries up fast in a crash — the buyers who normally absorb selling '
        "pressure step aside when uncertainty spikes, so even moderate selling can move prices "
        'sharply.",\n'
        '    "Historical crashes (2000, 2008, 2020) all share three elements: excessive '
        "leverage that forces selling when prices fall, a narrative shift that changes what "
        'investors think assets are worth, and a liquidity crunch that amplifies both."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "Not every large drawdown is a crash — a 10–15% correction is normal and '
        "happens in most years. A crash implies a faster, more disorderly decline driven by "
        'forced selling and loss of confidence.",\n'
        '    "Crashes are notoriously hard to predict in advance — most recoveries also happen '
        'faster than investors expect, which is why staying invested matters as much as '
        'avoiding the peak."\n'
        '  ]\n'
        "}\n\n"

        "Question: 'How will interest rates affect tech stocks?'\n"
        "{\n"
        '  "answer": "Higher interest rates tend to push tech stock valuations down because '
        "they make future earnings worth less in today's dollars — and tech companies derive "
        'most of their value from growth expected years from now.",\n'
        '  "bullets": [\n'
        '    "The mechanism: higher rates increase the \'discount rate\' used to value future '
        "profits. A dollar of earnings in year 5 becomes worth less today when rates rise — "
        'and growth companies have more of their value tied to distant future profits.",\n'
        '    "In practice: when the 10-year Treasury yield rises sharply, you typically see '
        "investors rotate out of high-multiple tech into banks, energy, and value stocks, "
        'which earn more of their profits now.",\n'
        '    "Watch the 10-year Treasury yield. If it rises above ~4.5–5%, the pressure on '
        "high-multiple tech becomes harder to ignore. Also watch whether the Fed signals "
        'a pause — markets often recover growth positions quickly when rate fears ease."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "This is a general rule — profitable tech companies with strong current cash '
        "flows (like Apple or Alphabet) tend to hold up better than unprofitable high-growth "
        'names during rate rises.",\n'
        '    "Watch the Fed\'s forward guidance and the 10-year yield trend — markets often '
        'price rate changes weeks before they happen."\n'
        '  ]\n'
        "}\n\n"

        "Question: 'What is a P/E ratio?'\n"
        "{\n"
        '  "answer": "A P/E ratio (price-to-earnings) tells you how much investors are paying '
        "for each dollar of a company's annual profit — a P/E of 20 means you're paying $20 "
        'for every $1 the company earns per year.",\n'
        '  "bullets": [\n'
        '    "How it works: divide the stock price by earnings per share. If a stock trades '
        "at $100 and earns $5 per share, the P/E is 20. The higher the P/E, the more "
        'investors are paying upfront relative to current profits.",\n'
        '    "How investors use it: a low P/E can signal a bargain or a struggling business; '
        "a high P/E usually signals growth expectations. S&P 500 average is roughly 15–20x; "
        'growth stocks often trade at 30–50x or higher.",\n'
        '    "Compare P/Es within the same sector — a 30x P/E might be cheap for a fast-growing '
        'software company but expensive for a slow-growth utility."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "P/E is backward-looking if based on trailing earnings. Forward P/E (using next '
        "year's estimated earnings) is usually more useful for growth companies — but earnings "
        'estimates can be wrong.",\n'
        '    "Watch earnings revisions: if analysts are cutting their EPS estimates, a \'cheap\' '
        'P/E can get cheaper fast."\n'
        '  ]\n'
        "}\n\n"

        f"{_format_evidence_section(evidence)}"
        f"━━━ USER QUESTION ━━━\n{question}\n\n"
        "Return only the JSON object. No prose before or after it."
    )


def general_fallback_prompt(question: str, evidence: Optional[List[RetrievedEvidence]] = None) -> str:
    """Construct a prompt for the general fallback agent.

    Used when a question does not cleanly match any specialized finance intent
    (company analysis, market question, investing education, portfolio question).
    Typical examples: broad economic questions, interdisciplinary questions
    (AI & productivity), historical/conceptual questions (why markets crash),
    or factual finance questions that don't fit a tighter bucket.

    The prompt answers the question directly without forcing a finance frame —
    but connects back to investing context in the bullets when natural.
    Output schema is identical to GeneralFinanceAnswer so the same rendering
    and fallback logic applies.

    Parameters
    ----------
    question : str   The user's question.
    evidence : list  Optional retrieved evidence; injected as "Current Context"
                     when provided.  Falls back to conceptual reasoning when empty.
    """
    return (
        "You are a knowledgeable analyst with broad expertise in economics, finance, "
        "and business. A user has asked a question that may or may not be directly "
        "about investing — answer it clearly and conversationally regardless.\n\n"

        "━━━ CRITICAL REQUIREMENT ━━━\n"
        "The 'answer' field MUST contain at least 2 full sentences answering the "
        "question that was actually asked. An empty answer is never acceptable.\n"
        "If you are uncertain, explain the general principle — that is always possible "
        "and always useful. Never leave 'answer' blank.\n\n"

        "━━━ TONE AND APPROACH ━━━\n"
        "- Answer the question directly — do not redirect away from it\n"
        "- Lead with the direct answer, not a caveat or framing sentence\n"
        "- Do NOT start with: 'This is a broad question', 'This is a macro question',\n"
        "  'Great question', 'As an AI', 'It depends', or any similar deflection\n"
        "- Use plain English — explain any technical terms you use\n"
        "- Use contractions naturally: it's, doesn't, that's, isn't\n"
        "- Do not pretend to have real-time data; if current data matters, say so briefly "
        "  in caveats — not in the answer itself\n"
        "- Where there is a natural connection to investing or financial markets, "
        "  draw it in the bullets — but don't force it if the question is non-financial\n\n"

        "━━━ OUTPUT STRUCTURE ━━━\n"
        "Produce exactly 3 fields in the JSON output:\n\n"

        "1. 'answer' (string — REQUIRED, minimum 2 sentences)\n"
        "   Answer the question directly. Explain the core concept or fact.\n"
        "   Lead with what the answer IS, not with what it depends on.\n\n"

        "2. 'bullets' (array of exactly 3 strings — REQUIRED)\n"
        "   Bullet 1 — The core mechanism, cause, or explanation: HOW or WHY\n"
        "   Bullet 2 — A concrete example, historical instance, or real-world implication\n"
        "   Bullet 3 — The investing or market angle (if one exists naturally); otherwise "
        "               a practical takeaway or what to watch\n\n"

        "3. 'caveats' (array of exactly 2 strings — REQUIRED)\n"
        "   Caveat 1 — A genuine qualification: when the answer differs, or what it depends on\n"
        "   Caveat 2 — What to watch, read further on, or a limit of this explanation\n\n"

        "━━━ EXAMPLES ━━━\n\n"

        "Question: 'How often does the Fed meet?'\n"
        "{\n"
        '  "answer": "The Federal Reserve\'s Federal Open Market Committee (FOMC) meets '
        "eight times per year on a scheduled basis — roughly every six to eight weeks. "
        'Emergency unscheduled meetings can also happen when conditions warrant.",\n'
        '  "bullets": [\n'
        '    "Each meeting runs two days, ending with a policy statement and a press conference '
        "by the Fed chair. The key output is a decision on the federal funds rate — raise, "
        'cut, or hold.",\n'
        '    "Markets pay close attention to the Fed\'s language, not just the rate decision. '
        "A single word change in the statement (like removing 'patient') can move markets "
        'as much as an actual rate change.",\n'
        '    "The meeting schedule is published in advance at federalreserve.gov. The most '
        "market-moving meetings are those where a rate change is expected — usually in "
        'March, June, September, and December."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "Scheduled meetings are separate from emergency sessions — the Fed can and does '
        'act between meetings in a crisis (as it did in March 2020).",\n'
        '    "Watch the meeting dates and the CME FedWatch tool, which shows the market\'s '
        'implied probability of a rate change going into each meeting."\n'
        '  ]\n'
        "}\n\n"

        "Question: 'How does AI affect productivity?'\n"
        "{\n"
        '  "answer": "AI raises productivity by automating repetitive tasks and accelerating '
        "knowledge work — the same output gets produced with less time and labour. "
        "The gains aren't uniform: they're largest in industries where information processing "
        'and pattern recognition are the main bottleneck.",\n'
        '  "bullets": [\n'
        '    "The mechanism: AI compresses the time needed for research, drafting, coding, '
        "analysis, and customer service. A task that took a skilled worker two hours might "
        'take twenty minutes with a capable AI tool.",\n'
        '    "In practice: early data from knowledge-work settings shows 20–40% task completion '
        "speed improvements for workers using AI tools vs those who don't — with the largest "
        'gains among less experienced workers.",\n'
        '    "For investors, the productivity angle matters for earnings: companies that '
        "successfully deploy AI to cut costs or expand capacity without proportional headcount "
        'growth can structurally improve margins."\n'
        '  ],\n'
        '  "caveats": [\n'
        '    "Aggregate productivity statistics are slow to capture these gains — the full '
        "economic impact of a new general-purpose technology like AI typically takes a decade "
        'or more to show up clearly in GDP figures.",\n'
        '    "Watch enterprise AI adoption rates and labour productivity data from the BLS — '
        'those are early signals of whether the AI productivity story is actually playing out."\n'
        '  ]\n'
        "}\n\n"

        f"{_format_evidence_section(evidence)}"
        f"━━━ USER QUESTION ━━━\n{question}\n\n"
        "Return only the JSON object. No prose before or after it."
    )