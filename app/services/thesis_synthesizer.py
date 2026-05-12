"""
Investment thesis synthesiser.

Combines outputs from all five specialist investment agents into a single,
balanced InvestmentThesis.  The synthesiser is the final stage of the
multi-agent company analysis pipeline:

  CompanyContext
      ↓ (retrieve_market_evidence)
  List[RetrievedEvidence]
      ↓ (five parallel specialist agents)
  ValuationView + MacroSensitivity + RiskProfile + MarketContext + QualityAssessment
      ↓ (this module)
  InvestmentThesis

Phase 4 governance checks run deterministically *after* the LLM synthesis
call, without re-invoking the model.  Any detected contradiction is appended
to InvestmentThesis.consistency_warnings so the frontend can surface it.

Usage
-----
    from app.services.thesis_synthesizer import synthesize_thesis
    from app.investment_agents import (
        run_valuation_agent, run_macro_agent, run_risk_agent,
        run_market_agent, run_quality_agent,
    )

    valuation = run_valuation_agent(company, evidence)
    macro     = run_macro_agent(company, evidence)
    risk      = run_risk_agent(company, evidence)
    market    = run_market_agent(company, evidence)
    quality   = run_quality_agent(company, evidence)

    thesis = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from ..structured_output import get_structured_response, extract_json_candidate, repair_data
from ..model_client import model_client
from ..config import settings
from .depth_guard import check_synthesis_depth
from .signal_ranker import rank_signals, compress_thesis as _compress_thesis, check_forbidden_phrases, RankedSignalSet

logger = logging.getLogger(__name__)


# ── Governance check constants ────────────────────────────────────────────────

# Known sector / macro contradictions: if a company is in these sectors,
# certain macro claims need extra scrutiny.
_RATE_SENSITIVE_SECTORS = frozenset({
    "Financials", "Real Estate", "Utilities",
})
_RATE_DEFENSIVE_SECTORS = frozenset({
    "Technology", "Consumer Discretionary",
})

# Phrases that assert "rate cuts help this company" — fine for most, but
# potentially misleading for banks (who benefit from higher rates via NIM).
_RATE_CUT_BENEFIT_PHRASES = (
    "rate cuts benefit",
    "lower rates benefit",
    "falling rates help",
    "rate cuts help",
    "benefits from lower rates",
)

# InvestmentThesis fields the LLM must populate (used in prompt + recovery).
# Ordered to match the schema's logical reading order.
_THESIS_FIELDS = (
    "ticker",
    "company_name",
    "direct_answer",
    "bull_thesis",
    "bear_thesis",
    "key_drivers",
    "key_risks",
    "valuation_view",
    "macro_sensitivity",
    "confidence_score",
    "confidence_reasoning",
    "what_changes_the_thesis",
    "conclusion",
)

# Markdown heading patterns used for recovery detection
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


# ── Evidence summary builders ─────────────────────────────────────────────────

def _evidence_block(evidence: List[RetrievedEvidence], max_items: int = 10) -> str:
    """Format top-N evidence items as a numbered block for the synthesis prompt."""
    top = sorted(evidence, key=lambda e: e.relevance_score, reverse=True)[:max_items]
    return "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(top)
    )


def _agent_block(label: str, overall: str, confidence: float) -> str:
    """Format one agent output as a plain-text block (no markdown headings)."""
    return (
        f"{label.upper()} AGENT (confidence {confidence:.0%}):\n"
        f"{overall or 'No analysis available.'}"
    )


# ── JSON field schema description (injected into prompt) ─────────────────────

_THESIS_SCHEMA_DESCRIPTION = """\
Required JSON fields (all must be present):
  "ticker"                  : string — the company ticker symbol (e.g. "AAPL")
  "company_name"            : string — canonical company name (e.g. "Apple Inc.")
  "direct_answer"           : string — 2-3 sentences that directly answer the user's exact \
question. MUST open with the mechanism (e.g. "Higher rates pressure AAPL via multiple \
compression because…"). MUST name at least one company-specific offset or amplifier. \
MUST NOT open with a generic company overview.
  "bull_thesis"             : string — 2-3 sentence bull case narrative
  "bear_thesis"             : string — 2-3 sentence bear case narrative
  "key_drivers"             : array of 4 strings — top value drivers, ranked by importance
  "key_risks"               : array of 4 strings — top investment risks, ranked by severity
  "valuation_view"          : string — 1-2 sentence valuation summary with specific multiple/metric
  "macro_sensitivity"       : string — 1-2 sentence macro sensitivity with specific transmission
  "confidence_score"        : number between 0.0 and 1.0
  "confidence_reasoning"    : string — why this confidence level was assigned
  "what_changes_the_thesis" : array of 4 strings — company-specific triggers that flip the thesis
  "conclusion"              : string — institutional-quality one-paragraph conclusion"""


# ── Synthesis prompt ──────────────────────────────────────────────────────────

def _build_synthesis_prompt(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
    original_user_question: Optional[str] = None,
    ranked: Optional[RankedSignalSet] = None,
) -> str:
    # Plain-text agent summaries — NO markdown headings to avoid bleeding into output
    agent_summaries = "\n\n".join([
        _agent_block("Valuation", valuation.overall, valuation.confidence),
        _agent_block("Macro Sensitivity", macro.overall, macro.confidence),
        _agent_block("Risk Profile", risk.overall, risk.confidence),
        _agent_block("Market Context", market.overall, market.confidence),
        _agent_block("Business Quality", quality.overall, quality.confidence),
    ])

    key_risks_txt = "\n".join(f"- {r}" for r in risk.key_risks) or "None identified."
    catalysts_txt = "\n".join(f"- {c}" for c in market.recent_catalysts) or "None identified."
    ev_block = _evidence_block(evidence)

    ticker = company.ticker

    # Build the ranked-signals injection block
    if ranked is not None and (ranked.top_signals or ranked.top_risks):
        signal_lines = []
        for i, sig in enumerate(ranked.top_signals[:3], 1):
            signal_lines.append(
                f"  SIGNAL {i} [{sig.signal_type.upper()}/{sig.direction.upper()}"
                f"/impact={sig.impact_score:.1f}]: {sig.signal}"
            )
        for i, sig in enumerate(ranked.top_risks[:3], 1):
            signal_lines.append(
                f"  RISK {i} [RISK/BEARISH/impact={sig.impact_score:.1f}]: {sig.signal}"
            )
        ranked_signals_section = (
            "PRE-RANKED SIGNALS (prioritize these — ranked by composite importance):\n"
            + "\n".join(signal_lines)
            + "\nYour synthesis MUST address each of these signals explicitly.\n"
        )
    else:
        ranked_signals_section = ""

    # Optional company business model section
    if profile is not None:
        biz_model_section = (
            f"COMPANY BUSINESS MODEL (ground every claim in this):\n"
            f"Business model: {profile.business_model}\n"
            f"Primary revenue drivers: {', '.join(profile.primary_revenue_drivers)}\n"
            f"Recurring revenue: {', '.join(profile.recurring_revenue_sources)}\n"
            f"Valuation style: {profile.valuation_style}\n"
            f"Key metrics: {', '.join(profile.key_metrics)}\n"
            f"Competitive advantages: {'; '.join(profile.competitive_advantages)}\n"
            f"Rate sensitivity: {profile.rate_sensitivity_note}\n"
        )
        profile_keywords_hint = (
            f"Required terms include: {', '.join(profile.business_model_keywords[:8])}."
            if profile.business_model_keywords
            else ""
        )
    else:
        biz_model_section = ""
        profile_keywords_hint = ""

    # Build the question-anchor block (injected only when a question is present)
    if original_user_question:
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"QUESTION-ANCHORED DIRECT ANSWER RULES (mandatory for \"direct_answer\" field):\n"
            f"- Sentence 1: State the PRIMARY mechanism by which this factor affects "
            f"{company.company_name} ({ticker}). Be concrete and specific "
            f'(e.g. "Higher rates compress {ticker}\'s ~28x P/E multiple because '
            f'long-duration cash flows are discounted at a higher rate.").\n'
            f"- Sentence 2: Name at least one {ticker}-specific offset, amplifier, or nuance "
            f"(e.g. Services recurring revenue, buyback program, net-cash balance sheet, "
            f"installed base, iPhone demand elasticity).\n"
            f"- FORBIDDEN: Opening with a generic company description "
            f'("Apple is a technology company…" or "Apple Inc. is a leading…").\n'
            f"- FORBIDDEN: Answering a different question than the one asked.\n"
            f"- REQUIRED: The mechanism must trace directly to {ticker}'s actual "
            f"business model and the macro/sector factor in the question.\n\n"
        )
    else:
        question_anchor_block = ""

    return f"""You are a senior investment analyst producing an institutional-quality investment thesis.

CRITICAL OUTPUT RULES — READ FIRST:
- You MUST return ONLY a single valid JSON object.
- Do NOT write any markdown headings, prose, or text outside the JSON.
- Do NOT use markdown code fences (no ```json or ```).
- Do NOT write "Investment Thesis for...", "Bull Case:", "Bear Case:" or any other headings.
- Your ENTIRE response must start with {{ and end with }}.
- Any non-JSON output will cause a parse failure.

COMPANY: {company.company_name} ({ticker})
Sector: {company.sector or "Unknown"} | Industry: {company.industry or "Unknown"}

{biz_model_section}
{question_anchor_block}{ranked_signals_section}
SPECIALIST AGENT OUTPUTS:
{agent_summaries}

Key Risks Identified:
{key_risks_txt}

Recent Catalysts:
{catalysts_txt}

SUPPORTING EVIDENCE:
{ev_block}

LANGUAGE RULES — MANDATORY:
FORBIDDEN (replace with causal mechanisms):
- "well positioned" → say HOW the position creates value
- "strong company" → cite FCF conversion %, credit rating, or specific metric
- "industry leader" → name the specific market share %, product, or advantage
- "robust ecosystem" → name the specific lock-in mechanism and switching cost
- "faces challenges" → name the specific challenge and its P&L transmission
- "investors should monitor" → name the specific data point and threshold

REQUIRED language: causal chains, mechanisms, specific metrics, asymmetry analysis.

AGENT CONFLICT ANALYSIS:
Before synthesising, identify any disagreements between agents:
- Does valuation say cheap while risk says high debt? (value trap risk)
- Does macro say rate cuts imminent while quality says margin pressures building?
- Does market say bullish catalysts while risk says near-term headwinds?
Explicitly address each conflict in your bull/bear thesis text.

TASK — produce a JSON object with exactly these fields:
0. direct_answer: 2-3 sentences that directly answer the user's exact question (see above).
   MUST open with the mechanism. MUST NOT open with a generic company overview.
1. bull_thesis: 2-3 sentences. MUST cite: (a) at least one specific {company.company_name} \
business segment or product, (b) at least one agent-identified driver, (c) a valuation anchor.
2. bear_thesis: 2-3 sentences. MUST cite: (a) a specific company-level risk, (b) a macro \
headwind's actual transmission mechanism to {ticker}'s earnings/margins.
3. key_drivers: exactly 4 drivers, ranked by importance, phrased as "{ticker}-specific: X"
4. key_risks: exactly 4 risks, ranked by severity, with company-specific transmission.
5. valuation_view: 1-2 sentences citing actual multiple or metric (not generic).
6. macro_sensitivity: 1-2 sentences on how the SPECIFIC macro environment hits \
{company.company_name}'s SPECIFIC revenue lines and cost structure.
7. confidence_score: 0.0-1.0. Penalise for low-confidence agent inputs and sparse evidence.
8. confidence_reasoning: Why this confidence level? Cite agent confidence levels.
9. what_changes_the_thesis: exactly 4 company-specific triggers (not generic macro events).
10. conclusion: Institutional-quality paragraph. Must NOT contain generic phrases \
like "the company faces headwinds" or "as a growth stock". MUST name specific \
{ticker} revenue drivers, risks, and valuation factors.

Agent reconciliation rules:
- If agents DISAGREE on direction, explicitly say WHY the stronger argument wins and \
what would flip you the other way.
- Rank key_drivers and key_risks by importance — put the most impactful first.
- Every claim must trace back to a specific agent output or evidence item number.

Company specificity rules (MANDATORY):
- You MUST mention {company.company_name}'s actual business segments/products.
- FORBIDDEN: Generic phrases like "tech companies face headwinds", "as a growth stock".
- REQUIRED: Specific {ticker} terms. {profile_keywords_hint}

{_THESIS_SCHEMA_DESCRIPTION}

Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


# ── Markdown stripping recovery ───────────────────────────────────────────────

def _strip_markdown_to_json(raw: str) -> Optional[str]:
    """Attempt to recover a JSON object from a markdown-prose response.

    When the LLM ignores the JSON-only instruction and returns markdown headings
    and paragraphs, this function:
      1. Detects markdown heading patterns.
      2. Strips all heading lines (##, ###, etc.) and code fences.
      3. Tries to find a JSON object in the cleaned text.
      4. Returns the JSON string if found, or None.

    This is a best-effort recovery — it does not reconstruct JSON from prose.
    """
    if not _MD_HEADING_RE.search(raw):
        return None  # Not a markdown response — caller handles normally

    print(f"[DIAG] THESIS SYNTHESIS MARKDOWN DETECTED — attempting markdown strip recovery")

    # Remove fenced code blocks
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    cleaned = cleaned.replace("```", "")

    # Remove markdown heading lines
    cleaned = _MD_HEADING_RE.sub("", cleaned)

    # Try to extract a JSON object from the cleaned text
    candidate = extract_json_candidate(cleaned)
    if candidate and candidate.strip().startswith("{"):
        return candidate

    return None


# ── Deterministic governance checks (Phase 4) ────────────────────────────────

def _check_rate_cut_bank_contradiction(
    company: CompanyContext,
    macro: MacroSensitivity,
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if thesis/macro text says 'rate cuts benefit' for a bank.

    Banks earn net-interest-margin income that typically shrinks when rates
    fall.  Asserting rate cuts help a bank without nuance is a contradiction.
    """
    warnings: List[str] = []
    if company.sector not in _RATE_SENSITIVE_SECTORS:
        return warnings

    combined_text = (
        (macro.overall + " " + thesis.bull_thesis + " " + thesis.macro_sensitivity)
        .lower()
    )
    if any(phrase in combined_text for phrase in _RATE_CUT_BENEFIT_PHRASES):
        warnings.append(
            f"[GOVERNANCE] Rate-cut benefit claim for {company.sector} company "
            f"({company.ticker}): banks and financials typically earn less NIM when "
            f"rates fall — verify this claim is appropriately nuanced."
        )
    return warnings


def _check_valuation_risk_tension(
    valuation: ValuationView,
    risk: RiskProfile,
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if valuation says 'cheap/undervalued' but risk says 'high debt'."""
    warnings: List[str] = []
    val_low = (valuation.overall + " " + valuation.relative_value).lower()
    risk_low = (risk.debt_risk + " " + risk.overall).lower()

    cheap_signals = ("cheap", "undervalued", "discount to peers", "low multiple")
    debt_signals = ("high debt", "high leverage", "elevated leverage", "overleveraged",
                    "refinancing risk", "debt burden")

    val_cheap = any(s in val_low for s in cheap_signals)
    high_debt  = any(s in risk_low for s in debt_signals)

    if val_cheap and high_debt:
        warnings.append(
            f"[GOVERNANCE] Valuation-risk tension for {thesis.ticker}: valuation "
            f"signals 'cheap/undervalued' while risk profile flags high debt. "
            f"A 'value trap' scenario should be explicitly addressed in the thesis."
        )
    return warnings


def _check_evidence_sparse(
    evidence: List[RetrievedEvidence],
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if thesis confidence is high but evidence is sparse."""
    warnings: List[str] = []
    if len(evidence) < 3 and thesis.confidence_score > 0.70:
        warnings.append(
            f"[GOVERNANCE] High confidence ({thesis.confidence_score:.0%}) with "
            f"only {len(evidence)} evidence item(s). Confidence score may be "
            f"overstated — recommend gathering more data before acting."
        )
    return warnings


def _run_governance_checks(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    thesis: InvestmentThesis,
    evidence: List[RetrievedEvidence],
) -> List[str]:
    """Run all Phase 4 deterministic consistency checks. Return warning strings."""
    warnings: List[str] = []
    warnings.extend(_check_rate_cut_bank_contradiction(company, macro, thesis))
    warnings.extend(_check_valuation_risk_tension(valuation, risk, thesis))
    warnings.extend(_check_evidence_sparse(evidence, thesis))
    return warnings


# ── Graceful empty thesis ─────────────────────────────────────────────────────

def _empty_thesis(
    company: CompanyContext,
    reason: str = "",
    original_user_question: Optional[str] = None,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker=company.ticker,
        company_name=company.company_name,
        direct_answer="",
        bull_thesis="Insufficient evidence to build a bull thesis.",
        bear_thesis="Insufficient evidence to build a bear thesis.",
        conclusion=f"Analysis incomplete. {reason}".strip(),
        confidence_score=0.0,
        confidence_reasoning="No sufficient evidence or agent outputs available.",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ── JSON-only LLM call with markdown recovery ─────────────────────────────────

def _call_with_json_enforcement(
    prompt: str,
    ticker: str,
    max_retries: int,
    backoff_factor: float,
    request_id: Optional[str] = None,
) -> Optional[InvestmentThesis]:
    """Call the model and enforce JSON-only output for InvestmentThesis.

    Wraps get_structured_response with thesis-specific diagnostics and a
    pre-validation markdown-stripping recovery path.  Returns a validated
    InvestmentThesis or None if all attempts fail.
    """
    import time

    for attempt in range(1, max_retries + 1):
        # ── Model call ────────────────────────────────────────────────────────
        try:
            call_kwargs: Dict[str, Any] = {}
            if request_id:
                call_kwargs["request_id"] = request_id
            raw = model_client.call(prompt, **call_kwargs)
        except Exception as exc:
            logger.warning("[thesis_synthesizer] model call failed attempt=%d: %r", attempt, exc)
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        raw_len = len(raw) if raw else 0
        print(
            f"[DIAG] THESIS SYNTHESIS RAW "
            f"ticker={ticker} attempt={attempt} len={raw_len}\n"
            f"[DIAG] THESIS SYNTHESIS RAW TEXT: {raw!r:.1000}"
        )

        # ── Markdown recovery (before JSON extraction) ────────────────────────
        if raw and _MD_HEADING_RE.search(raw):
            recovered = _strip_markdown_to_json(raw)
            if recovered:
                print(
                    f"[DIAG] THESIS SYNTHESIS PARSED "
                    f"ticker={ticker} attempt={attempt} source=markdown_recovery "
                    f"candidate={recovered!r:.400}"
                )
                try:
                    data = json.loads(recovered)
                except json.JSONDecodeError:
                    data = None
            else:
                print(
                    f"[DIAG] THESIS SYNTHESIS PARSED "
                    f"ticker={ticker} attempt={attempt} source=markdown_recovery_failed"
                )
                data = None
        else:
            # Normal JSON extraction path
            candidate = extract_json_candidate(raw) if raw else ""
            print(
                f"[DIAG] THESIS SYNTHESIS PARSED "
                f"ticker={ticker} attempt={attempt} source=json_extract "
                f"candidate={candidate!r:.400}"
            )
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                data = None

        if data is None:
            logger.warning(
                "[thesis_synthesizer] JSON parse failed attempt=%d ticker=%s",
                attempt, ticker,
            )
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        # ── Schema validation ─────────────────────────────────────────────────
        from pydantic import ValidationError
        try:
            if hasattr(InvestmentThesis, "model_validate"):
                result = InvestmentThesis.model_validate(data)
            else:
                result = InvestmentThesis.parse_obj(data)
            print(
                f"[DIAG] THESIS SYNTHESIS VALIDATED "
                f"ticker={ticker} attempt={attempt} "
                f"confidence={result.confidence_score} "
                f"bull_len={len(result.bull_thesis)} "
                f"bear_len={len(result.bear_thesis)}"
            )
            return result
        except ValidationError as ve:
            logger.warning(
                "[thesis_synthesizer] validation failed attempt=%d: %s", attempt, ve
            )
            # Attempt repair
            repaired = repair_data(data, InvestmentThesis)
            try:
                if hasattr(InvestmentThesis, "model_validate"):
                    result = InvestmentThesis.model_validate(repaired)
                else:
                    result = InvestmentThesis.parse_obj(repaired)
                print(
                    f"[DIAG] THESIS SYNTHESIS VALIDATED "
                    f"ticker={ticker} attempt={attempt} source=repaired "
                    f"confidence={result.confidence_score}"
                )
                return result
            except ValidationError:
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue

    logger.error(
        "[thesis_synthesizer] all %d attempts failed for %s", max_retries, ticker
    )
    return None


# ── Public entry point ────────────────────────────────────────────────────────

def synthesize_thesis(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
    original_user_question: Optional[str] = None,
) -> InvestmentThesis:
    """Synthesise agent outputs into an InvestmentThesis.

    Runs the LLM synthesis with strict JSON-only enforcement, then applies
    deterministic Phase 4 governance checks and Phase 5 depth enforcement.
    Degrades gracefully if the LLM call fails.

    Parameters
    ----------
    company               : Normalised company identity.
    valuation             : Output from run_valuation_agent().
    macro                 : Output from run_macro_agent().
    risk                  : Output from run_risk_agent().
    market                : Output from run_market_agent().
    quality               : Output from run_quality_agent().
    evidence              : Full evidence list (all agents' inputs combined).
    request_id            : Optional trace ID forwarded to model client.
    profile               : Optional CompanyKnowledgeProfile; enables richer prompting
                            and depth-guard checks when supplied.
    original_user_question: The user's verbatim question. When supplied the synthesiser
                            produces a ``direct_answer`` field that specifically addresses
                            the question before the broader thesis.

    Returns
    -------
    InvestmentThesis with consistency_warnings populated by governance and
    depth-guard layers.
    """
    print(
        f"[thesis_synthesizer] synthesising for {company.ticker} "
        f"({len(evidence)} evidence items, "
        f"val_conf={valuation.confidence:.2f} "
        f"macro_conf={macro.confidence:.2f} "
        f"risk_conf={risk.confidence:.2f} "
        f"market_conf={market.confidence:.2f} "
        f"quality_conf={quality.confidence:.2f})"
    )

    # Check if all agents returned empty outputs (all-zero confidence)
    agent_confidences = [
        valuation.confidence, macro.confidence,
        risk.confidence, market.confidence, quality.confidence,
    ]
    if all(c == 0.0 for c in agent_confidences) and not evidence:
        print(f"[thesis_synthesizer] all agents empty + no evidence — skipping LLM call")
        return _empty_thesis(company, "No agent outputs or evidence available.")

    # ── Phase 3: Signal ranking (pre-synthesis) ───────────────────────────────
    # Run before the LLM call so ranked signals can be injected into the prompt.
    try:
        ranked = rank_signals(
            valuation, macro, risk, market, quality,
            company=company, profile=profile,
        )
    except Exception as exc:
        logger.warning("[thesis_synthesizer] signal_ranker failed: %r — continuing", exc)
        ranked = None

    prompt = _build_synthesis_prompt(
        company, valuation, macro, risk, market, quality, evidence, profile,
        original_user_question=original_user_question,
        ranked=ranked,
    )

    # ── JSON-enforced LLM call with markdown recovery ─────────────────────────
    thesis = _call_with_json_enforcement(
        prompt=prompt,
        ticker=company.ticker,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        request_id=request_id,
    )

    if thesis is None:
        logger.warning("[thesis_synthesizer] synthesis failed for %s", company.ticker)
        return _empty_thesis(company, "LLM synthesis error: retries exhausted.")

    # Stamp metadata
    thesis.ticker = company.ticker
    thesis.company_name = company.company_name
    thesis.evidence_count = len(evidence)
    thesis.generated_at = datetime.now(timezone.utc).isoformat()

    # ── Attach ranked signals to thesis ──────────────────────────────────────
    if ranked is not None:
        thesis.top_signals = ranked.top_signals
        thesis.top_risks = ranked.top_risks
        thesis.secondary_signals = ranked.secondary_signals

    # ── Phase 4: governance / consistency checks ──────────────────────────────
    warnings = _run_governance_checks(company, valuation, macro, risk, thesis, evidence)

    # ── Phase 5: depth enforcement ────────────────────────────────────────────
    depth_warnings = check_synthesis_depth(thesis, company, profile)
    warnings = warnings + depth_warnings

    # ── Phase 5+: forbidden phrase quality check ──────────────────────────────
    quality_warnings = check_forbidden_phrases(thesis)
    warnings = warnings + quality_warnings

    thesis.consistency_warnings = warnings

    if warnings:
        for w in warnings:
            print(w)

    # ── Phase 4: thesis compression ───────────────────────────────────────────
    if ranked is not None:
        try:
            thesis.compressed_thesis = _compress_thesis(thesis, ranked)
            thesis.one_sentence_thesis = thesis.compressed_thesis.one_sentence_thesis
        except Exception as exc:
            logger.warning("[thesis_synthesizer] compression failed: %r", exc)

    print(
        f"[thesis_synthesizer] done for {company.ticker}: "
        f"confidence={thesis.confidence_score:.2f} "
        f"warnings={len(warnings)} "
        f"(governance={len(warnings) - len(depth_warnings) - len(quality_warnings)}, "
        f"depth={len(depth_warnings)}, quality={len(quality_warnings)}) "
        f"top_signals={len(thesis.top_signals)} "
        f"top_risks={len(thesis.top_risks)}"
    )
    return thesis
