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

import logging
from datetime import datetime, timezone
from typing import List, Optional

from ..schemas import (
    CompanyContext,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

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


# ── Evidence summary builders ─────────────────────────────────────────────────

def _evidence_block(evidence: List[RetrievedEvidence], max_items: int = 10) -> str:
    """Format top-N evidence items as a numbered block for the synthesis prompt."""
    top = sorted(evidence, key=lambda e: e.relevance_score, reverse=True)[:max_items]
    return "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(top)
    )


def _agent_block(label: str, overall: str, confidence: float) -> str:
    return f"### {label} (confidence {confidence:.0%})\n{overall or 'No analysis available.'}"


# ── Synthesis prompt ──────────────────────────────────────────────────────────

def _build_synthesis_prompt(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    evidence: List[RetrievedEvidence],
) -> str:
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

    return f"""You are a senior investment analyst producing an institutional-quality thesis.

COMPANY: {company.company_name} ({company.ticker})
Sector: {company.sector or "Unknown"} | Industry: {company.industry or "Unknown"}

=== SPECIALIST AGENT OUTPUTS ===
{agent_summaries}

Key Risks Identified:
{key_risks_txt}

Recent Catalysts:
{catalysts_txt}

=== SUPPORTING EVIDENCE ===
{ev_block}

=== TASK ===
Synthesise the agent outputs into a balanced InvestmentThesis. Requirements:
1. bull_thesis: 2-3 sentence bull case grounded in valuation, quality, and catalysts.
2. bear_thesis: 2-3 sentence bear case grounded in risks and macro headwinds.
3. key_drivers: exactly 4 value drivers as bullet strings.
4. key_risks: exactly 4 investment risks as bullet strings.
5. valuation_view: 1-2 sentence valuation summary.
6. macro_sensitivity: 1-2 sentence macro sensitivity summary.
7. confidence_score: 0.0-1.0. Penalise for low-confidence agent inputs and sparse evidence.
8. confidence_reasoning: Why this confidence level?
9. what_changes_the_thesis: exactly 4 events/data-points that would materially change the view.
10. conclusion: one concise paragraph synthesising the overall investment merit.

Rules:
- Be specific — cite ticker, sector, and evidence numbers where relevant.
- Avoid generic phrases like "the company faces headwinds" without specifics.
- If evidence is sparse, say so explicitly in confidence_reasoning.
- Do NOT fabricate financial figures not present in the evidence."""


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

def _empty_thesis(company: CompanyContext, reason: str = "") -> InvestmentThesis:
    return InvestmentThesis(
        ticker=company.ticker,
        company_name=company.company_name,
        bull_thesis="Insufficient evidence to build a bull thesis.",
        bear_thesis="Insufficient evidence to build a bear thesis.",
        conclusion=f"Analysis incomplete. {reason}".strip(),
        confidence_score=0.0,
        confidence_reasoning="No sufficient evidence or agent outputs available.",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


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
) -> InvestmentThesis:
    """Synthesise agent outputs into an InvestmentThesis.

    Runs the LLM synthesis then applies deterministic Phase 4 governance
    checks.  Degrades gracefully if the LLM call fails.

    Parameters
    ----------
    company   : Normalised company identity.
    valuation : Output from run_valuation_agent().
    macro     : Output from run_macro_agent().
    risk      : Output from run_risk_agent().
    market    : Output from run_market_agent().
    quality   : Output from run_quality_agent().
    evidence  : Full evidence list (all agents' inputs combined).
    request_id: Optional trace ID forwarded to model client.

    Returns
    -------
    InvestmentThesis with consistency_warnings populated by governance layer.
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

    prompt = _build_synthesis_prompt(
        company, valuation, macro, risk, market, quality, evidence
    )

    try:
        thesis = get_structured_response(
            prompt,
            InvestmentThesis,
            model_client,
            max_retries=settings.model_max_retries,
            backoff_factor=settings.model_backoff_factor,
            request_id=request_id,
        )
    except Exception as exc:
        logger.warning("thesis_synthesizer LLM failed for %s: %r", company.ticker, exc)
        return _empty_thesis(company, f"LLM synthesis error: {exc}")

    # Stamp metadata
    thesis.ticker = company.ticker
    thesis.company_name = company.company_name
    thesis.evidence_count = len(evidence)
    thesis.generated_at = datetime.now(timezone.utc).isoformat()

    # ── Phase 4: governance / consistency checks ──────────────────────────────
    warnings = _run_governance_checks(company, valuation, macro, risk, thesis, evidence)
    thesis.consistency_warnings = warnings

    if warnings:
        for w in warnings:
            print(w)

    print(
        f"[thesis_synthesizer] done for {company.ticker}: "
        f"confidence={thesis.confidence_score:.2f} "
        f"warnings={len(warnings)}"
    )
    return thesis
