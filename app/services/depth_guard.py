"""
Post-generation depth enforcement for investment theses.

Checks that synthesised theses are genuinely company-specific rather than
generic macro summaries with company names inserted.  Warnings are appended
to InvestmentThesis.consistency_warnings by the synthesiser (same pattern
as the Phase 4 governance checks).
"""

from __future__ import annotations

from typing import List, Optional

from ..schemas import CompanyContext, CompanyKnowledgeProfile, InvestmentThesis

# ── Generic phrases that signal overly-broad synthesis ───────────────────────

_GENERIC_PHRASES = (
    "tech companies face",
    "the company faces headwinds",
    "as a growth stock",
    "like many companies",
    "the broader market",
    "industry as a whole",
    "sector as a whole",
)

# ── Valuation language keywords ───────────────────────────────────────────────

_VALUATION_TERMS = (
    "p/e",
    "multiple",
    "dcf",
    "discount rate",
    "earnings",
    "margin",
    "revenue",
    "valuation",
    "free cash flow",
    "fcf",
    "ev/",
    "price-to",
)


def check_synthesis_depth(
    thesis: InvestmentThesis,
    company: CompanyContext,
    profile: Optional[CompanyKnowledgeProfile] = None,
) -> List[str]:
    """Check that a synthesised thesis is company-specific, not generic.

    Runs up to five deterministic checks and returns a list of warning
    strings (prefixed "[DEPTH]").  An empty list means the thesis is
    acceptably specific.

    Parameters
    ----------
    thesis  : The synthesised InvestmentThesis to evaluate.
    company : Normalised company identity (ticker + name).
    profile : Optional CompanyKnowledgeProfile; enables keyword-density
              and revenue-driver checks when supplied.

    Returns
    -------
    List[str] — zero or more depth-guard warning strings.
    """
    warnings: List[str] = []

    ticker = company.ticker
    company_name = company.company_name

    # Build the full thesis text used for most checks
    full_text = " ".join(filter(None, [
        thesis.bull_thesis,
        thesis.bear_thesis,
        thesis.conclusion,
        " ".join(thesis.key_drivers),
    ]))
    full_text_lower = full_text.lower()

    # Also build the combined bull + bear + conclusion text for the generic-phrase check
    bbc_text = " ".join(filter(None, [
        thesis.bull_thesis,
        thesis.bear_thesis,
        thesis.conclusion,
    ])).lower()

    # ── Check 1: company reference ────────────────────────────────────────────
    if ticker.lower() not in full_text_lower and company_name.lower() not in full_text_lower:
        warnings.append(
            f"[DEPTH] Thesis text does not reference {ticker} by name — "
            f"synthesis may be a generic sector summary rather than a "
            f"{company_name}-specific thesis."
        )

    # ── Check 2: business model keyword density (requires profile) ────────────
    if profile is not None:
        found_keywords: List[str] = []
        for kw in profile.business_model_keywords:
            if kw.lower() in full_text_lower:
                found_keywords.append(kw)
        if len(found_keywords) < 3:
            found_display = ", ".join(f"'{k}'" for k in found_keywords) if found_keywords else "none"
            warnings.append(
                f"[DEPTH] Only {len(found_keywords)} company-specific term(s) found in thesis "
                f"(found: {found_display}). Synthesis may be overly generic for {ticker}."
            )

    # ── Check 3: valuation language ───────────────────────────────────────────
    if not any(term in full_text_lower for term in _VALUATION_TERMS):
        warnings.append(
            f"[DEPTH] Thesis contains no valuation-specific language for {ticker}."
        )

    # ── Check 4: generic phrase detector ─────────────────────────────────────
    generic_hits = [phrase for phrase in _GENERIC_PHRASES if phrase in bbc_text]
    if len(generic_hits) >= 2:
        warnings.append(
            f"[DEPTH] {len(generic_hits)} generic sector-level phrase(s) detected. "
            f"Synthesis should use company-specific reasoning."
        )

    # ── Check 5: primary revenue driver mention (requires profile) ────────────
    if profile is not None and profile.primary_revenue_drivers:
        # Strip parenthetical annotations (e.g. "iPhone (~52% of revenue)" → "iphone")
        # so the check matches the core product/segment name rather than the full
        # annotated string (which would never appear verbatim in the thesis text).
        driver_mentioned = any(
            driver.split("(")[0].split(",")[0].strip().lower() in full_text_lower
            for driver in profile.primary_revenue_drivers
            if driver.split("(")[0].split(",")[0].strip()
        )
        if not driver_mentioned:
            drivers_list = ", ".join(profile.primary_revenue_drivers)
            warnings.append(
                f"[DEPTH] Thesis does not mention any of {ticker}'s primary revenue "
                f"drivers ({drivers_list}). Key business model context is missing."
            )

    return warnings
