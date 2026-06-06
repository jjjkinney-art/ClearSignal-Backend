"""Q-First question answerer agent (Phase 4 / Option B).

Generates a direct_answer BEFORE the thesis synthesis pipeline runs,
so the answer is derived from the question + profile + evidence rather
than being a compressed byproduct of the conviction thesis.

Architecture:
    question + intent + CompanyKnowledgeProfile + evidence
        ↓
    run_question_answerer()
        ↓
    direct_answer (str, 4-6 sentences, intent-specific format)
        ↓ (passed to synthesize_thesis as pre_synthesized_answer)
    Investment Thesis synthesis (uses pre_synthesized_answer verbatim)

The CompanyKnowledgeProfile is a first-class input here — not a prompt
decoration.  Its recession_behavior, competitive_advantages,
recurring_revenue_sources, and valuation_style fields contain the
company-specific facts that make direct_answer specific rather than generic.

For most intents the agent can answer directly from the profile + evidence.
For intents requiring external data (historical_precedent, quantitative_threshold),
the evidence block is critical; the profile provides the company-specific context.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, CompanyKnowledgeProfile, RetrievedEvidence
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "question_answerer_agent"

# Maximum evidence items passed to the Q-First call.
# We want the most relevant items only — the agent is making a focused call,
# not a full synthesis.
_MAX_EVIDENCE_ITEMS = 12


def _select_evidence(
    evidence: List[RetrievedEvidence],
    question: str,
    intent: str,
) -> List[RetrievedEvidence]:
    """Select the most relevant evidence items for the Q-First call.

    Priority:
    1. Items whose title contains the question's key terms.
    2. Intent-specific keyword matches.
    3. FMP/financial data items (always useful for quantitative intents).
    """
    q_lower = question.lower()
    intent_keywords = {
        "implied_growth_rate":    ["p/e", "pe", "forward", "valuation", "multiple", "growth rate", "estimate"],
        "timing_lag":             ["capex", "revenue", "backlog", "guidance", "lag", "quarter", "data center"],
        "quantitative_threshold": ["loss", "exposure", "loan", "reserve", "charge", "eps", "roe", "income"],
        "metric_ordering":        ["comparable", "membership", "same-store", "renewal", "recession", "growth"],
        "segment_ranking":        ["segment", "revenue", "margin", "moat", "cloud", "productivity", "business"],
        "historical_precedent":   ["historical", "prior", "cycle", "growth", "multiple", "comparable"],
        "risk_assessment":        ["risk", "geopolit", "taiwan", "conflict", "earnings", "transmission"],
        "competitive_position":   ["pricing", "customer", "market share", "competitor", "moat"],
        "valuation_stance":       ["p/e", "pe", "premium", "multiple", "valuation", "earnings"],
    }
    kw_list = intent_keywords.get(intent, [])

    scored: list[tuple[int, RetrievedEvidence]] = []
    for ev in evidence:
        score = 0
        title_l = ev.title.lower()
        source_l = ev.source.lower()
        # FMP / financial data items are always highly relevant for quantitative calls
        if "fmp" in source_l or "financial" in source_l or "valuation" in source_l:
            score += 3
        # Intent keyword match
        score += sum(1 for kw in kw_list if kw in title_l or kw in source_l)
        # Question term match (rough: long words from the question)
        q_terms = [t for t in q_lower.split() if len(t) > 5]
        score += sum(1 for t in q_terms if t in title_l)
        scored.append((score, ev))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ev for _, ev in scored[:_MAX_EVIDENCE_ITEMS]]


def _profile_block(profile: Optional[CompanyKnowledgeProfile], company: CompanyContext) -> str:
    """Build the profile context block for the Q-First prompt."""
    if profile is None:
        return ""

    lines = [
        "=== COMPANY KNOWLEDGE PROFILE (ClearSignal proprietary data) ===",
        f"Business model: {profile.business_model}",
        f"Valuation style: {profile.valuation_style}",
    ]

    if profile.recurring_revenue_sources:
        lines.append(
            f"Recurring revenue sources: {', '.join(profile.recurring_revenue_sources[:5])}"
        )
    if profile.recession_behavior:
        lines.append(f"Recession behavior: {profile.recession_behavior}")
    if profile.competitive_advantages:
        lines.append(
            f"Competitive advantages: {'; '.join(profile.competitive_advantages[:4])}"
        )
    if profile.major_risks:
        lines.append(f"Major risks: {'; '.join(profile.major_risks[:3])}")
    if profile.primary_revenue_drivers:
        lines.append(
            f"Primary revenue drivers: {', '.join(profile.primary_revenue_drivers[:5])}"
        )
    if profile.key_metrics:
        lines.append(
            f"Key metrics to watch: {', '.join(profile.key_metrics[:5])}"
        )
    lines.append("=== END PROFILE ===")
    return "\n".join(lines)


def _evidence_block(evidence: List[RetrievedEvidence]) -> str:
    if not evidence:
        return "No external evidence available."
    return "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )


# ── Per-intent prompt templates ───────────────────────────────────────────────

_INTENT_PROMPTS = {

    "implied_growth_rate": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (financial data, analyst estimates, valuation ratios):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer to the question above.

Sentence 1 — State {ticker}'s current forward P/E or EV/Revenue multiple (use evidence data).
  Then compute the implied compound revenue or EPS CAGR that multiple requires over 3–5 years.
  Use: implied_CAGR ≈ (required_earnings_in_year_N / current_earnings)^(1/N) - 1
  where required_earnings is anchored to what would justify the current multiple at a terminal P/E of 20-25x.
  Format: "At ~[X]x forward P/E, the market is pricing in approximately [Y]% compound revenue growth
  over [N] years to justify the multiple at a terminal ~[Z]x."

Sentence 2 — State the current analyst consensus growth estimate from evidence.
  Explicitly compare: does consensus meet, exceed, or fall short of the implied rate?
  Format: "Analyst consensus projects ~[X]% revenue CAGR, which [meets / falls short of / exceeds]
  the implied [Y]% by [Z] percentage points."

Sentence 3 — Name 1-2 historical analogs: company, period, multiple at entry, and whether
  they sustained the implied growth rate. Use evidence if available; use training knowledge
  for well-known cases (Cisco 2000, Qualcomm 2014, etc.) only if evidence is absent.
  Format: "Historical analog: [Company] in [period] carried a ~[X]x multiple requiring ~[Y]%
  growth — [outcome: they sustained it / they fell short by Z% / the stock rerating took N years]."

Sentence 4 — State whether the implied growth rate is achievable given {ticker}'s profile,
  and the single data point that would confirm or deny it.
  Format: "[Achievable / Stretched / Requires execution perfection] — the key variable is [metric]:
  if [specific threshold], the growth rate is defensible; if not, the multiple faces [X]% compression."

RULES:
- Do NOT open with company description.
- Do NOT hedge with "it depends" without providing a directional answer.
- Use actual numbers from evidence for the multiple. If forward P/E is unavailable, use trailing P/E.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "timing_lag": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (financial data, recent news, guidance):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer about the timing lag asked about.

Sentence 1 — State the typical lag in quarters with a specific range.
  Format: "Historically, the lag from [upstream event: capex decision / policy change / X]
  to [{ticker}'s specific revenue line: Data Center / Services / Loans] impact is
  approximately [X]–[Y] quarters."
  Use evidence where available; use the profile's business model description where evidence
  is thin. Do not invent numbers — say "approximately 2–3 quarters based on order cycle
  patterns" rather than fabricating precision.

Sentence 2 — Walk the causal chain step by step.
  Format: "[Upstream decision] → [order placement / contract signed / inventory adjustment]
  (lag: [X] weeks) → [backlog / pipeline stage] (lag: [Y] weeks) → [{ticker}'s]
  [specific revenue line] recognition (lag: [Z] quarters total)."

Sentence 3 — Quantify the revenue exposure: what % of {ticker}'s total revenue is exposed
  to this specific lag pathway at current run-rates? Use evidence data or profile data.
  Format: "[Segment name] represents approximately [X]% of {ticker}'s total revenue at
  ~[$Y]B annualized, so a [scenario: 25% capex deceleration] would reduce this segment
  by approximately $[Z]B over the lag period."

Sentence 4 — Name the leading indicator {ticker} or industry participants disclose that
  provides the earliest visibility into the lag materializing.
  Format: "The earliest leading indicator is [specific metric: hyperscaler capex guidance /
  order backlog / channel inventory] — {ticker} discloses this [quarterly / in earnings calls /
  in 10-Q section X]. A move below [threshold] would signal the lag is beginning."

RULES:
- Give a specific quarter range. "Several quarters" is not acceptable.
- Name the specific revenue segment ({ticker}'s actual segment name, not generic).
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "quantitative_threshold": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (financial data, balance sheet, loan book, analyst estimates):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer about the quantitative threshold asked about.

Sentence 1 — State the specific financial exposure from evidence.
  For credit/loan questions: "JPMorgan's [CRE office / consumer / X] exposure is approximately
  $[X]B as of the most recent disclosure."
  For revenue/segment questions: "[Segment] represents approximately $[X]B or [Y]% of total revenue."
  Use evidence data. If exact figure is unavailable, use the range from evidence.

Sentence 2 — Compute the threshold impact at the rate(s) the question asks about.
  Show the arithmetic: "At a [X]% loss/decline rate on $[Y]B exposure: impact = $[Z]B.
  Against [EPS of $A / ROE of B%], this represents approximately [C]% EPS dilution
  [or D basis points of ROE compression]."
  If the question asks for multiple scenarios (10%, 20%, 30%), compute each:
  "At 10%: ~$[X]B, ~[Y]% EPS impact. At 20%: ~$[A]B, ~[B]% EPS impact.
  At 30%: ~$[C]B, ~[D]% EPS impact."

Sentence 3 — Compare to historical stress: what loss/decline rate occurred in the most
  comparable period (2008-2009 GFC, 2020 COVID, 2001 recession)?
  Format: "In [crisis period], comparable [loan category / segment] experienced [X]% loss rates,
  producing [Y]% EPS impact. Current reserves cover approximately [Z] quarters at that rate."

Sentence 4 — State the probability scenario and the single trigger that would confirm
  the threshold is being approached.
  Format: "The [10% / 20% / X%] scenario requires [specific condition: office vacancy above Y%,
  rent concessions above Z%, etc.], which [is / is not] currently materializing based on
  [specific evidence item or public data]."

RULES:
- Do NOT refuse to quantify. Use evidence data and compute approximate impacts.
- If the exact exposure figure is not in evidence, use the figure from the question text itself.
- Show arithmetic in Sentence 2, even if approximate.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "metric_ordering": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (recent performance, historical data, analyst commentary):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer naming which metric deteriorates first and
in what order.

CRITICAL: Use the company's recession_behavior field from the profile above (if available).
This contains ClearSignal's proprietary analysis of how this company specifically behaves
in downturns — use it as primary evidence, not just background.

Sentence 1 — Name the FIRST metric to deteriorate and the causal mechanism.
  Must name an actual metric from the question (e.g., "comparable store sales",
  "membership renewal rates", "net new member growth", or whatever the question asks about).
  Causal mechanism: WHY does this metric lead in a downturn?
  Format: "[Metric A] deteriorates first because [specific mechanism: it is reported monthly
  with no smoothing / it is the most discretionary component / it responds to consumer
  confidence within [X] weeks]."

Sentence 2 — Name the SECOND metric to deteriorate and the lag.
  Format: "[Metric B] deteriorates second, typically [X] months after [Metric A], because
  [causal link: decisions take longer / contracts have renewal windows / the mechanism]."

Sentence 3 — Name the MOST RECESSION-RESISTANT metric and its structural protection.
  Format: "[Metric C] is most recession-resistant because [profile-specific reason:
  membership is paid annually and has a [X]% renewal rate / recurring contracts /
  X years of recession data shows it declined only Y%]."
  Use profile data (recession_behavior, recurring_revenue_sources) here.

Sentence 4 — Name the single metric an investor should watch as the earliest signal
  that recession pressure is building for this company specifically.
  Format: "The earliest recession signal for {ticker} is [specific metric] —
  [where/how disclosed] — because it leads the earnings impact by approximately [X] quarters."

RULES:
- Name ALL metrics asked about in the question and rank all of them.
- Use the recession_behavior profile field as primary evidence for historical behavior.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "segment_ranking": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (recent performance data, analyst commentary, competitive landscape):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer ranking the segments asked about.

CRITICAL: Use the competitive_advantages and recurring_revenue_sources fields from the
profile above (if available). These contain ClearSignal's proprietary moat analysis
for this specific company — use them as primary evidence.

Sentence 1 — State the COMPLETE ranked order, naming all segments from the question.
  Format: "#1: [Segment] — [primary moat source in 5 words]. #2: [Segment] — [reason].
  #3: [Segment] — [reason]." (adjust for however many segments the question asks about)
  Do not hedge or refuse to rank. Give a definitive ordering.

Sentence 2 — Explain the #1 segment's moat in structural terms.
  Name the specific type: switching costs, network effects, regulatory protection,
  IP/technical lead, or distribution advantage.
  Quantify: margin %, renewal rate %, or market share % if available in evidence or profile.
  Format: "[Segment #1]'s moat rests on [mechanism]. [Specific quantification from evidence
  or profile]. This advantage [is / is not] structurally durable because [reason]."

Sentence 3 — Explain the LAST-ranked segment's vulnerability.
  What specific threat — competitive, structural, or cyclical — most threatens its position?
  Format: "[Segment #last] is most vulnerable to [specific threat] because [mechanism].
  The risk is [quantified if possible: market share could fall X% if Y occurs]."

Sentence 4 — Name the ONE metric shift that could change the ranking.
  Format: "The ranking could change if [specific metric] in [specific segment] moves to
  [threshold]: at that level, [Segment X] would [surpass / fall below] [Segment Y] because
  [mechanism]."

RULES:
- Name ALL segments from the question in Sentence 1. Never omit a segment.
- "All segments have strong moats" is not an acceptable answer.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "historical_precedent": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (historical financial data, market data, research):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer providing the historical precedent asked about.

Sentence 1 — Name the BEST historical analog: a specific company, time period, and the
  relevant metric trajectory.
  Format: "[Company] from [year] to [year]: carried ~[X]x [multiple], required ~[Y]%
  compound growth to justify, and [outcome: achieved it / sustained it for Z years then
  decelerated / the stock rerating played out as follows]."
  Use training knowledge for well-documented cases (Cisco, Qualcomm, Intel, Walmart, etc.)
  since historical data is often not in the evidence block.

Sentence 2 — State the KEY SIMILARITY between the historical case and {ticker}'s
  current situation. What makes this a valid analog?
  Format: "The similarity: [both had X characteristic], [metric Y was at comparable level],
  [structural dynamic Z was present in both cases]."

Sentence 3 — State the KEY DIFFERENCE — what structural factor makes {ticker}'s
  situation more or less favorable than the historical case?
  Format: "The key difference: {ticker} [has / lacks] [specific structural advantage or
  disadvantage] that [Company] did not [have / face], which [amplifies / mitigates]
  the [risk / opportunity] compared to the historical case."

Sentence 4 — State the implication for {ticker}'s current situation.
  If the analog holds: what happens to the multiple or growth trajectory?
  If it doesn't hold: what would distinguish this case?
  Format: "If the analog holds, {ticker}'s [multiple / growth trajectory] faces [outcome]
  over [timeframe]. The distinguishing factor that would invalidate the analog is [specific
  condition]."

RULES:
- Name a SPECIFIC company and period. "There are historical examples..." is not acceptable.
- Use training knowledge for well-documented historical cases — the evidence may not contain it.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    # For existing intents: lighter-touch version that uses profile + evidence
    # to produce a more specific answer than the synthesis mandate alone.
    "risk_assessment": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE:
{evidence_block}

TASK: Produce a precise 4-sentence direct answer to this risk question.

Sentence 1 — Name {ticker}'s #1 risk for this specific scenario: the mechanism,
  who/what it comes from, and which P&L line or structural position it threatens.
  Be specific to the scenario in the question.

Sentence 2 — State the transmission channel: how does the risk propagate through
  the business? [trigger] → [first-order P&L impact] → [second-order structural impact].

Sentence 3 — Name the specific trigger that would confirm this risk is materializing.
  What data point, event, or threshold signals it has gone from risk to reality?

Sentence 4 — State how investors should discount for it: what probability would justify
  the current multiple, and what would justify a material re-rating lower?

RULES:
- Name specific companies, geographies, revenue lines, and mechanisms.
- Do not list general sector risks. Answer specifically for {ticker}'s situation.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "valuation_stance": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE (valuation ratios, analyst estimates):
{evidence_block}

TASK: Produce a precise 4-sentence direct answer on valuation stance.

Sentence 1 — State the verdict explicitly: overpriced / fairly valued / underpriced,
  and name the primary anchoring metric (forward P/E, EV/EBITDA, FCF yield, or
  analyst consensus target vs current price).

Sentence 2 — If this is a premium-comparison question: state whether the premium is
  structurally justified by naming the specific structural advantage that commands it
  (e.g., membership fee recurring revenue, switching costs, market share premium).

Sentence 3 — State what growth or execution assumption the current price requires to
  be justified. Be specific: "The current multiple requires [X]% revenue growth and
  [Y]% margin stability over [N] years."

Sentence 4 — Name the single metric that would cause the premium / multiple to compress.
  Format: "The most likely compression trigger is [metric] falling below [threshold]
  because [specific mechanism for this company]."

RULES:
- Do not open with company description.
- Commit to a verdict. "It depends" without a directional lean is not acceptable.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    "competitive_position": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE:
{evidence_block}

TASK: Produce a precise 4-sentence direct answer to this competitive / moat question.

Sentence 1 — Directly answer the specific question asked (pricing power, moat source,
  customer relationship, competitive ceiling). Use profile data (competitive_advantages)
  as the primary source.

Sentence 2 — Quantify: name market share %, margin premium, switching cost, or pricing
  ceiling where available in evidence or profile.

Sentence 3 — Name the specific competitive risk: which competitor, which product or
  workload is at risk, and the mechanism of displacement.

Sentence 4 — State the single metric that would confirm the moat is holding or eroding.

RULES:
- Name specific customers, products, and competitors from the question.
- Use the competitive_advantages profile field as primary evidence.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",

    # Generic fallback for investment_thesis and business_model
    "investment_thesis": """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE:
{evidence_block}

TASK: Produce a precise 4-sentence direct answer to this investment question.

Sentence 1 — State the PRIMARY mechanism that directly answers what the question asks.
  Be specific to {ticker}'s business model (use profile data).

Sentence 2 — State whether the business model driver is sustainable under the scenario
  in the question. Name the specific mechanism.

Sentence 3 — Name the single most important operating metric to watch for confirmation.

Sentence 4 — State the specific condition or data point that would change the answer.

RULES:
- Do not open with generic company description.
- Use profile data (business_model, primary_revenue_drivers) as primary source.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
""",
}

# Use business_model as an alias for investment_thesis
_INTENT_PROMPTS["business_model"] = _INTENT_PROMPTS["investment_thesis"]
# Use macro_sensitivity (Q-First provides lighter-touch — the macro agent covers depth)
_INTENT_PROMPTS["macro_sensitivity"] = """\
You are a financial analyst. Your ONE job is to answer this specific question:

USER'S EXACT QUESTION: "{question}"

COMPANY: {name} ({ticker})

{profile_block}

EVIDENCE:
{evidence_block}

TASK: Produce a precise 4-sentence direct answer about the macro sensitivity asked about.

Sentence 1 — State the PRIMARY transmission channel: [macro move] → [specific mechanism]
  → [specific P&L or multiple impact] for {ticker}. Quantify direction and magnitude.

Sentence 2 — State {ticker}'s most important offset or insulation: recurring revenue,
  rate-insensitive earnings, balance sheet strength, or pricing power.

Sentence 3 — Quantify the sensitivity where evidence allows
  (e.g., "100bps rate move ≈ X% P/E compression" or "10% capex cut ≈ $Y revenue impact").

Sentence 4 — Name the threshold at which the macro scenario becomes a material risk
  vs a manageable headwind for {ticker} specifically.

RULES:
- Trace through {ticker}'s specific revenue structure. "Rates affect growth stocks" is forbidden.
- Use profile recession_behavior and recurring_revenue_sources fields.
- Return ONLY the 4-sentence answer as plain text. No JSON, no headers, no bullet points.
"""


def run_question_answerer(
    question: str,
    intent: str,
    company: CompanyContext,
    profile: Optional[CompanyKnowledgeProfile],
    evidence: List[RetrievedEvidence],
) -> str:
    """Generate a direct answer to the user's question before thesis synthesis.

    Called by _run_investment_pipeline immediately after evidence retrieval and
    profile loading, BEFORE the 5 specialist agents run (or concurrently with them
    via the thread pool — caller decides).

    The answer is passed to synthesize_thesis as pre_synthesized_answer and
    injected into the synthesis prompt so the final thesis is built around this
    answer rather than treating it as a compressed byproduct.

    Parameters
    ----------
    question : The verbatim user question.
    intent   : The classified question intent (from _detect_question_intent).
    company  : CompanyContext with ticker and company_name.
    profile  : CompanyKnowledgeProfile — FIRST-CLASS INPUT. Provides recession_behavior,
               competitive_advantages, recurring_revenue_sources, etc.
    evidence : Full evidence list; a focused subset is selected internally.

    Returns
    -------
    str — a 4-sentence direct answer, or "" if the call fails (pipeline continues
    without pre-synthesized answer; synthesis falls back to mandate-only mode).
    """
    # Select focused evidence for this call
    selected_evidence = _select_evidence(evidence, question, intent)

    # Get the per-intent prompt template
    template = _INTENT_PROMPTS.get(intent, _INTENT_PROMPTS["investment_thesis"])

    profile_text = _profile_block(profile, company)
    evidence_text = _evidence_block(selected_evidence)

    prompt = template.format(
        question=question,
        name=company.company_name,
        ticker=company.ticker,
        profile_block=profile_text,
        evidence_block=evidence_text,
    )

    print(
        f"[question_answerer] running for {company.ticker} "
        f"intent={intent!r} evidence={len(selected_evidence)} items"
    )

    try:
        from openai.types.chat import ChatCompletionMessageParam
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": (
                    "You are a precise financial analyst. Follow the TASK instructions exactly. "
                    "Return ONLY the requested plain-text sentences. "
                    "Do not add headers, bullet points, or JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = model_client.client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.3,   # Lower temperature for precision
            max_tokens=600,    # 4-6 sentences fits in ~400 tokens; 600 gives headroom
        )
        raw = response.choices[0].message.content or ""
        answer = raw.strip()
        if not answer:
            logger.warning(
                "[question_answerer] empty response for %s intent=%s",
                company.ticker, intent,
            )
            return ""
        print(
            f"[question_answerer] completed for {company.ticker}: "
            f"{len(answer)} chars"
        )
        return answer
    except Exception as exc:
        logger.warning(
            "[question_answerer] failed for %s intent=%s: %r",
            company.ticker, intent, exc,
        )
        return ""
