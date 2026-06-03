"""
Post-generation depth enforcement for investment theses.

Checks that synthesised theses are genuinely company-specific rather than
generic macro summaries with company names inserted.  Warnings are appended
to InvestmentThesis.consistency_warnings by the synthesiser (same pattern
as the Phase 4 governance checks).

Severity-4 changes (2026-06-03)
--------------------------------
* Check 5 now accepts sub-product names inside driver parentheses as
  alternative match terms (e.g. "Azure" matches "Intelligent Cloud (... Azure
  IaaS/PaaS ...)").  Eliminates false positives where the LLM correctly
  names the product but not the official segment label.
* inject_revenue_context() — called by the synthesiser when Check 5 fires
  — appends a compact revenue breakdown line to thesis.conclusion so the
  output always surfaces key business model context even when the LLM elides it.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

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


def _driver_alternatives(driver: str) -> List[str]:
    """Return a list of match terms for a single revenue driver string.

    The primary term is everything before the first '(' or ','.  Additional
    terms are extracted from the parenthetical content: the portion after
    '—' or ':' is split on commas and the first word of each token is added
    when it is at least 3 characters long.

    Example
    -------
    "Intelligent Cloud (~43% of revenue — Azure IaaS/PaaS, SQL Server)"
        → ["Intelligent Cloud", "Azure", "SQL"]

    "AWS (~17% of revenue, ~65-70% of operating income)"
        → ["AWS"]
    """
    main = driver.split("(")[0].split(",")[0].strip()
    alternatives: List[str] = [main] if main else []

    # Extract from inside parentheses
    paren_match = re.search(r"\(([^)]+)\)", driver)
    if paren_match:
        paren = paren_match.group(1)
        # Focus on the part after an em-dash or colon
        for sep in ("—", "–", ":"):
            if sep in paren:
                paren = paren.split(sep, 1)[1]
                break
        for token in paren.split(","):
            word = token.strip().split()[0].rstrip("/").strip() if token.strip() else ""
            # Skip percentage tokens and short tokens
            if len(word) >= 3 and not word.startswith("~") and not word.startswith("%"):
                alternatives.append(word)

    return alternatives


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
    # Severity-4 improvement: accept sub-product names inside parentheses as
    # alternatives to the official segment label.  A thesis that mentions "Azure"
    # satisfies the "Intelligent Cloud" driver check; a thesis that mentions
    # "Ozempic" satisfies the "GLP-1 diabetes" driver check.
    if profile is not None and profile.primary_revenue_drivers:
        driver_mentioned = any(
            any(alt.lower() in full_text_lower
                for alt in _driver_alternatives(driver))
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


def inject_revenue_context(
    thesis: InvestmentThesis,
    profile: CompanyKnowledgeProfile,
) -> InvestmentThesis:
    """Append a compact revenue context line to thesis.conclusion.

    Called by the synthesiser when Check 5 fires and cannot be resolved via
    profile keyword matching.  Ensures the output always surfaces the top-3
    revenue drivers even when the LLM elides segment-level detail.

    The injected line is prefixed with a delimiter so the frontend can strip
    or style it separately if desired.

    Returns the mutated thesis (modifies in-place via attribute assignment).
    """
    if not profile.primary_revenue_drivers:
        return thesis

    # Take the top 3 drivers, strip verbose parenthetical detail for readability
    top3: List[str] = []
    for drv in profile.primary_revenue_drivers[:3]:
        # Keep the main name and the first parenthetical token (e.g. "~17% of revenue")
        main = drv.split("(")[0].strip()
        paren_match = re.search(r"\(([^)]+)\)", drv)
        pct = ""
        if paren_match:
            first_token = paren_match.group(1).split(",")[0].split("—")[0].strip()
            if first_token:
                pct = f" ({first_token})"
        top3.append(f"{main}{pct}")

    context_line = (
        f" | Business model context: "
        + "; ".join(top3)
        + "."
    )

    existing = thesis.conclusion or ""
    # Avoid double-injection on retry paths
    if "Business model context:" not in existing:
        thesis.conclusion = existing.rstrip() + context_line

    return thesis
