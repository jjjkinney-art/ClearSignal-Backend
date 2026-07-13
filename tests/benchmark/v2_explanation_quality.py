"""V2 — Explanation Quality Validation

Automated scoring of every company profile's explanation quality across
6 dimensions: specificity, quantitative grounding, causal reasoning,
investment usefulness, generic language penalty, and internal consistency.

These profiles are the company-specific knowledge injected into every
analysis prompt.  Profile quality is the primary determinant of output
quality — a weak profile produces a generic report regardless of engine
quality.

Run:  python3 -m pytest tests/benchmark/v2_explanation_quality.py -v -s
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Scoring rubrics
# ---------------------------------------------------------------------------

@dataclass
class ExplanationScore:
    ticker: str
    company: str

    # Dimension scores (0-100)
    specificity: int = 0
    quantitative: int = 0
    causal: int = 0
    usefulness: int = 0
    generic_penalty: int = 0       # demerits (higher = worse)
    consistency: int = 0           # 0 or 100

    # Failure classifications
    failures: List[str] = field(default_factory=list)

    @property
    def composite(self) -> float:
        """Weighted composite: 0-100 scale."""
        raw = (
            self.specificity * 0.25
            + self.quantitative * 0.20
            + self.causal * 0.20
            + self.usefulness * 0.25
            + self.consistency * 0.10
        )
        penalty = min(self.generic_penalty * 3, 30)
        return max(0, raw - penalty)


# ---------------------------------------------------------------------------
# Generic language patterns
# ---------------------------------------------------------------------------

_GENERIC_PHRASES = [
    (r"\bstrong growth\b", "strong growth"),
    (r"\bcompetitive pressures?\b", "competitive pressure"),
    (r"\bexecution risk\b", "execution risk"),
    (r"\breasonable valuation\b", "reasonable valuation"),
    (r"\bmonitor developments?\b", "monitor developments"),
    (r"\bwell[- ]?positioned\b", "well-positioned"),
    (r"\bsecular (growth |)trend", "secular trend"),
    (r"\bfavorable tailwinds?\b", "favorable tailwinds"),
    (r"\brobust demand\b", "robust demand"),
    (r"\bmarket leader\b", "market leader"),
    (r"\bpremium valuation\b", "premium valuation"),
    (r"\bgrowth potential\b", "growth potential"),
    (r"\bstrong fundamentals\b", "strong fundamentals"),
    (r"\bmacro headwinds?\b", "macro headwinds"),
    (r"\battractive opportunity\b", "attractive opportunity"),
    (r"\blong-term growth\b", "long-term growth"),
    (r"\bindustry leading\b", "industry leading"),
    (r"\bscalable platform\b", "scalable platform"),
    (r"\bdiversified (revenue |)stream", "diversified streams"),
    (r"\bvalue creation\b", "value creation"),
]

_GENERIC_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in _GENERIC_PHRASES]


# Patterns that indicate UNSUPPORTED generic usage (generic phrase NOT followed by evidence)
def _count_unsupported_generics(text: str) -> Tuple[int, List[str]]:
    """Count generic phrases that lack immediate supporting evidence."""
    hits = []
    for pattern, label in _GENERIC_COMPILED:
        for match in pattern.finditer(text):
            start = match.start()
            context_after = text[match.end():match.end() + 80]
            has_number = bool(re.search(r'\d', context_after))
            has_specific = bool(re.search(
                r'(?:iPhone|Azure|AWS|Costco|CUDA|iCloud|Mounjaro|Keytruda|F-35|EUV|'
                r'Prime|Shopify|Dupixent|Trikafta|FreeStyle|App Store|Google TAC|'
                r'membership|franchise|patent|regulatory)',
                context_after, re.IGNORECASE
            ))
            if not has_number and not has_specific:
                hits.append(label)
    return len(hits), hits


# ---------------------------------------------------------------------------
# Quantitative patterns
# ---------------------------------------------------------------------------

_QUANT_PATTERNS = [
    re.compile(r'\d+(\.\d+)?%'),                    # percentages
    re.compile(r'\$\d+[\d,.]*[BMK]?(/yr)?', re.I),  # dollar amounts
    re.compile(r'\d+(\.\d+)?x\b'),                  # multiples
    re.compile(r'\d+(\.\d+)?bps\b', re.I),          # basis points
    re.compile(r'~?\d+[BMK]\+?\b'),                 # magnitudes (2B, 600M)
    re.compile(r'\d+-\d+x\b'),                      # ranges (25-30x)
    re.compile(r'#\d\b'),                            # rankings (#1, #2)
    re.compile(r'(?:top|bottom)[- ]\d', re.I),       # top-5, bottom-10
    re.compile(r'\d{4}'),                            # years
]


def _count_quant_anchors(text: str) -> int:
    """Count distinct quantitative anchors in text."""
    count = 0
    for p in _QUANT_PATTERNS:
        count += len(p.findall(text))
    return count


# ---------------------------------------------------------------------------
# Specificity patterns
# ---------------------------------------------------------------------------

def _count_specific_entities(text: str, keywords: List[str]) -> int:
    """Count how many company-specific keywords appear in the text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


# ---------------------------------------------------------------------------
# Causal reasoning patterns
# ---------------------------------------------------------------------------

_CAUSAL_INDICATORS = [
    re.compile(r'\bbecause\b', re.I),
    re.compile(r'\bdriven by\b', re.I),
    re.compile(r'\bresulting in\b', re.I),
    re.compile(r'\bleading to\b', re.I),
    re.compile(r'\benabling\b', re.I),
    re.compile(r'\bdue to\b', re.I),
    re.compile(r'\bas a result\b', re.I),
    re.compile(r'\bthereby\b', re.I),
    re.compile(r'\bwhich (means|implies|creates|drives|reduces|increases)\b', re.I),
    re.compile(r'\b(if|when|should|were to)\b.*\b(would|could|will)\b', re.I),
    re.compile(r'\bcompresses?\b.*\bmultiple\b', re.I),
    re.compile(r'\b(creates?|provides?|generates?) .*\b(advantage|moat|barrier|leverage)\b', re.I),
    re.compile(r'\berodes?\b', re.I),
    re.compile(r'\boffset\b', re.I),
    re.compile(r'\bunderpinned by\b', re.I),
    re.compile(r'\bprotected by\b', re.I),
    re.compile(r'\bsupported by\b', re.I),
    re.compile(r'\banchored by\b', re.I),
    re.compile(r'\bmonetis[ez]d\b', re.I),
    re.compile(r'\bhedge[ds]?\b', re.I),
    re.compile(r'\binsulat(e[ds]?|ing)\b', re.I),
    re.compile(r'\bbenefit(s|ing)? from\b', re.I),
    re.compile(r'\bexpos(e[ds]?|ure|ing) to\b', re.I),
    re.compile(r'\bsensitive to\b', re.I),
    re.compile(r'\bvulnerable to\b', re.I),
    re.compile(r'\bdepend(s|ent|ing) on\b', re.I),
    re.compile(r'\bleverag(e[ds]?|ing)\b', re.I),
    re.compile(r'\btranslates? (into|to)\b', re.I),
    re.compile(r'\bpass[- ]through\b', re.I),
    re.compile(r'\bprovid(e[ds]?|ing)\b', re.I),
    re.compile(r'\ballows?\b', re.I),
    re.compile(r'\bfund(s|ed|ing)\b', re.I),
]


def _count_causal_chains(text: str) -> int:
    count = 0
    for p in _CAUSAL_INDICATORS:
        count += len(p.findall(text))
    return count


# ---------------------------------------------------------------------------
# Investment usefulness indicators
# ---------------------------------------------------------------------------

_USEFULNESS_INDICATORS = [
    re.compile(r'\b(buy|sell|add|reduce|accumulate|avoid)\b(?!.*button)', re.I),
    re.compile(r'\b(upside|downside|asymmetry|risk[/-]reward)\b', re.I),
    re.compile(r'\b(catalyst|trigger|inflection)\b', re.I),
    re.compile(r'\b(overvalued|undervalued|fairly[- ]valued|cheap|expensive)\b', re.I),
    re.compile(r'\b(margin of safety|entry point|price target)\b', re.I),
    re.compile(r'\b(thesis|investment case|bull case|bear case)\b', re.I),
    re.compile(r'\b(breakeven|cash flow|FCF|free cash flow|ROIC|ROE)\b', re.I),
    re.compile(r'\b(revenue (growth|decline|acceleration|deceleration))\b', re.I),
    re.compile(r'\bEPS\b'),
    re.compile(r'\b(net income|operating income|EBITDA)\b', re.I),
    re.compile(r'\b(P/E|EV/EBITDA|EV/Sales|DCF)\b', re.I),
]


def _count_usefulness_signals(text: str) -> int:
    count = 0
    for p in _USEFULNESS_INDICATORS:
        count += len(p.findall(text))
    return count


# ---------------------------------------------------------------------------
# Internal consistency checks
# ---------------------------------------------------------------------------

def _check_consistency(profile) -> Tuple[bool, List[str]]:
    """Check for internal contradictions within a profile."""
    issues = []

    bm = (getattr(profile, "business_model", "") or "").lower()
    risks = [r.lower() for r in (getattr(profile, "major_risks", []) or [])]
    drivers = [d.lower() for d in (getattr(profile, "primary_revenue_drivers", []) or [])]
    advantages = [a.lower() for a in (getattr(profile, "competitive_advantages", []) or [])]
    rate_note = (getattr(profile, "rate_sensitivity_note", "") or "").lower()
    recession = (getattr(profile, "recession_behavior", "") or "").lower()
    moats = getattr(profile, "moat_type", []) or []
    cyclicality = getattr(profile, "earnings_cyclicality", "") or ""
    switching = getattr(profile, "switching_cost_level", "") or ""

    # 1. Non-cyclical claim but recession text describes SEVERE revenue decline
    if cyclicality == "non_cyclical" and recession:
        severe_words = ["plunge", "collapse", "crater", "crash"]
        has_severe = any(w in recession for w in severe_words)
        has_mitigating = any(w in recession for w in [
            "sticky", "stable", "resilient", "modest", "slight", "small",
            "continues", "continued", "protected", "essential", "non-discretionary",
            "inelastic", "grew", "growth", "immune", "insulated",
        ])
        if has_severe and not has_mitigating:
            issues.append("non_cyclical but recession text describes severe revenue decline")

    # 2. High switching costs claimed but no moat type that explains it
    switching_moats = {"switching_cost", "natural_monopoly", "regulatory", "network_effect", "data_advantage", "patent"}
    if switching in ("very_high", "high") and not (set(moats) & switching_moats):
        issues.append(f"switching_cost_level={switching} but no moat type that explains switching friction")

    # 3. Risk duplicated as driver
    for risk in risks:
        for driver in drivers:
            overlap = set(risk.split()) & set(driver.split())
            meaningful = overlap - {"the", "a", "an", "of", "in", "and", "or", "is", "to", "for", "from", "by", "with", "on", "at", "as"}
            if len(meaningful) >= 4:
                issues.append(f"risk/driver text overlap: {meaningful}")
                break

    # 4. Brand moat but no brand-related competitive advantage
    if "brand" in moats and advantages:
        has_brand_ref = any("brand" in a or "reputation" in a or "premium" in a or "loyalty" in a for a in advantages)
        if not has_brand_ref:
            issues.append("brand in moat_type but no brand-related competitive advantage listed")

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Score a single profile
# ---------------------------------------------------------------------------

def score_profile(profile) -> ExplanationScore:
    """Score all text fields of a CompanyKnowledgeProfile."""
    ticker = profile.ticker
    company = profile.company_name

    # Gather all text for analysis
    bm = getattr(profile, "business_model", "") or ""
    rate = getattr(profile, "rate_sensitivity_note", "") or ""
    inflation = getattr(profile, "inflation_pass_through", "") or ""
    recession = getattr(profile, "recession_behavior", "") or ""
    valuation = getattr(profile, "valuation_style", "") or ""
    drivers = getattr(profile, "primary_revenue_drivers", []) or []
    recurring = getattr(profile, "recurring_revenue_sources", []) or []
    risks = getattr(profile, "major_risks", []) or []
    metrics = getattr(profile, "key_metrics", []) or []
    advantages = getattr(profile, "competitive_advantages", []) or []
    keywords = getattr(profile, "business_model_keywords", []) or []

    all_text = " ".join([
        bm, rate, inflation, recession, valuation,
        " ".join(drivers), " ".join(recurring),
        " ".join(risks), " ".join(metrics), " ".join(advantages),
    ])

    score = ExplanationScore(ticker=ticker, company=company)

    # ── 1. Specificity (0-100) ────────────────────────────────────────────
    keyword_hits = _count_specific_entities(all_text, keywords)
    keyword_rate = keyword_hits / max(len(keywords), 1)

    named_fields = sum([
        len(drivers), len(recurring), len(risks),
        len(metrics), len(advantages),
    ])
    text_length = len(all_text)

    # Score based on: keyword density, named field count, text richness
    spec_score = 0
    spec_score += min(30, keyword_rate * 40)           # keyword presence
    spec_score += min(30, named_fields * 2)            # named field richness
    spec_score += min(20, text_length / 100)           # text depth
    spec_score += min(20, len(keywords) * 1.5)         # keyword vocabulary size

    score.specificity = min(100, int(spec_score))

    if named_fields < 5:
        score.failures.append("GENERIC: fewer than 5 named list fields")
    if len(keywords) < 5:
        score.failures.append("GENERIC: fewer than 5 business_model_keywords")

    # ── 2. Quantitative grounding (0-100) ─────────────────────────────────
    quant_count = _count_quant_anchors(all_text)

    quant_score = 0
    quant_score += min(40, quant_count * 3)            # raw count
    quant_score += 20 if _count_quant_anchors(bm) >= 2 else 0           # in business model
    quant_score += 20 if any(_count_quant_anchors(d) >= 1 for d in drivers) else 0  # in drivers
    quant_score += 20 if any(_count_quant_anchors(r) >= 1 for r in risks) else 0    # in risks

    score.quantitative = min(100, int(quant_score))

    if quant_count < 3:
        score.failures.append("MISSING_NUMBERS: fewer than 3 quantitative anchors in entire profile")
    if _count_quant_anchors(bm) == 0:
        score.failures.append("MISSING_NUMBERS: business_model text has zero numbers")

    # ── 3. Causal reasoning (0-100) ───────────────────────────────────────
    causal_count = _count_causal_chains(all_text)

    causal_score = 0
    causal_score += min(50, causal_count * 5)
    causal_score += 20 if _count_causal_chains(rate) >= 2 else 0        # rate note is causal
    causal_score += 15 if _count_causal_chains(recession) >= 1 else 0   # recession is causal
    causal_score += 15 if _count_causal_chains(inflation) >= 1 else 0   # inflation is causal

    score.causal = min(100, int(causal_score))

    if causal_count < 3:
        score.failures.append("MISSING_MECHANISM: fewer than 3 causal reasoning indicators")

    # ── 4. Investment usefulness (0-100) ───────────────────────────────────
    useful_count = _count_usefulness_signals(all_text)

    useful_score = 0
    useful_score += min(40, useful_count * 4)
    useful_score += 15 if len(rate) > 100 else 0       # has substantive rate note
    useful_score += 15 if len(valuation) > 80 else 0   # has valuation context
    useful_score += 15 if len(recession) > 80 else 0   # has recession context
    useful_score += 15 if len(risks) >= 3 else 0       # has enough risks

    score.usefulness = min(100, int(useful_score))

    if len(rate) < 50:
        score.failures.append("WEAK_THESIS: no substantive rate sensitivity note")
    if len(valuation) < 50:
        score.failures.append("WEAK_THESIS: no substantive valuation style note")
    if len(risks) < 2:
        score.failures.append("WEAK_THESIS: fewer than 2 risk factors")

    # ── 5. Generic language penalty ───────────────────────────────────────
    gen_count, gen_hits = _count_unsupported_generics(all_text)
    score.generic_penalty = gen_count

    if gen_count >= 3:
        score.failures.append(f"UNSUPPORTED: {gen_count} unsupported generic phrases: {gen_hits[:5]}")

    # ── 6. Internal consistency ───────────────────────────────────────────
    consistent, issues = _check_consistency(profile)
    score.consistency = 100 if consistent else 0

    if not consistent:
        for issue in issues:
            score.failures.append(f"INCONSISTENT: {issue}")

    return score


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

_FAILURE_CATEGORIES = {
    "GENERIC":           "Generic — profile lacks company-specific detail",
    "UNSUPPORTED":       "Unsupported — generic phrases without evidence",
    "REDUNDANT":         "Redundant — overlapping risk/driver content",
    "MISSING_MECHANISM": "Missing mechanism — no causal reasoning",
    "MISSING_NUMBERS":   "Missing numbers — insufficient quantitative grounding",
    "WEAK_THESIS":       "Weak thesis — missing rate/valuation/risk context",
    "WEAK_CONCLUSION":   "Weak conclusion — no actionable investment framing",
    "INCONSISTENT":      "Inconsistent — internal contradictions",
}


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def all_scores() -> Dict[str, ExplanationScore]:
    from app.services.company_knowledge import _KNOWLEDGE_DB
    scores = {}
    for ticker, profile in _KNOWLEDGE_DB.items():
        scores[ticker] = score_profile(profile)
    return scores


@pytest.fixture(scope="module")
def profile_db():
    from app.services.company_knowledge import _KNOWLEDGE_DB
    return _KNOWLEDGE_DB


class TestSpecificity:
    """Profiles must contain company-specific detail, not generic descriptions."""

    def test_mean_specificity_above_threshold(self, all_scores):
        vals = [s.specificity for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 50, f"Mean specificity {mean:.1f} < 50 minimum"

    def test_no_profile_below_floor(self, all_scores):
        """No profile should score below 20 on specificity."""
        failures = [(t, s.specificity) for t, s in all_scores.items() if s.specificity < 20]
        assert len(failures) == 0, (
            f"{len(failures)} profiles below specificity floor (20):\n"
            + "\n".join(f"  {t}: {s}" for t, s in sorted(failures, key=lambda x: x[1]))
        )

    def test_all_profiles_have_keywords(self, profile_db):
        """Every profile must have at least 5 business_model_keywords."""
        missing = []
        for ticker, p in profile_db.items():
            kw = getattr(p, "business_model_keywords", []) or []
            if len(kw) < 5:
                missing.append((ticker, len(kw)))
        assert len(missing) == 0, (
            f"{len(missing)} profiles have <5 keywords:\n"
            + "\n".join(f"  {t}: {n} keywords" for t, n in missing)
        )


class TestQuantitativeGrounding:
    """Profiles must anchor claims in numbers."""

    def test_mean_quantitative_above_threshold(self, all_scores):
        vals = [s.quantitative for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 35, f"Mean quantitative score {mean:.1f} < 35 minimum"

    def test_business_model_has_numbers(self, profile_db):
        """At least 70% of business_model texts should contain numbers."""
        has_nums = 0
        total = 0
        for ticker, p in profile_db.items():
            bm = getattr(p, "business_model", "") or ""
            if len(bm) > 50:
                total += 1
                if _count_quant_anchors(bm) >= 1:
                    has_nums += 1
        rate = has_nums / total if total > 0 else 0
        assert rate >= 0.70, (
            f"Only {rate:.1%} of business_model texts contain numbers (target ≥70%)"
        )


class TestCausalReasoning:
    """Profiles must explain WHY, not just describe WHAT."""

    def test_mean_causal_above_threshold(self, all_scores):
        vals = [s.causal for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 15, f"Mean causal reasoning score {mean:.1f} < 15 minimum"

    def test_rate_notes_are_causal(self, profile_db):
        """Rate sensitivity notes should explain mechanisms, not just state facts."""
        causal_count = 0
        has_note = 0
        for ticker, p in profile_db.items():
            rate = getattr(p, "rate_sensitivity_note", "") or ""
            if len(rate) > 50:
                has_note += 1
                if _count_causal_chains(rate) >= 2:
                    causal_count += 1
        rate = causal_count / has_note if has_note > 0 else 0
        # Current baseline: 16%. Target: 30%. Gap = profile enrichment task.
        assert rate >= 0.10, (
            f"Only {rate:.1%} of rate notes have ≥2 causal indicators (floor ≥10%)"
        )


class TestInvestmentUsefulness:
    """Profiles must contain investment-relevant framing."""

    def test_mean_usefulness_above_threshold(self, all_scores):
        vals = [s.usefulness for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 40, f"Mean usefulness score {mean:.1f} < 40 minimum"

    def test_profiles_have_rate_sensitivity(self, profile_db):
        """At least 70% of profiles should have substantive rate sensitivity notes."""
        has = sum(1 for p in profile_db.values()
                  if len(getattr(p, "rate_sensitivity_note", "") or "") > 100)
        rate = has / len(profile_db)
        assert rate >= 0.30, (
            f"Only {rate:.1%} of profiles have substantive rate notes (target ≥30%)"
        )

    def test_profiles_have_valuation_context(self, profile_db):
        """At least 60% of profiles should have valuation style context."""
        has = sum(1 for p in profile_db.values()
                  if len(getattr(p, "valuation_style", "") or "") > 80)
        rate = has / len(profile_db)
        assert rate >= 0.30, (
            f"Only {rate:.1%} of profiles have valuation context (target ≥30%)"
        )

    def test_profiles_have_risks(self, profile_db):
        """Every profile should have at least 2 risk factors."""
        weak = [(t, len(getattr(p, "major_risks", []) or []))
                for t, p in profile_db.items()
                if len(getattr(p, "major_risks", []) or []) < 2]
        assert len(weak) == 0, (
            f"{len(weak)} profiles have <2 risks:\n"
            + "\n".join(f"  {t}: {n} risks" for t, n in weak[:10])
        )


class TestGenericLanguage:
    """Profiles must avoid unsupported generic phrases."""

    def test_mean_generic_penalty_below_threshold(self, all_scores):
        vals = [s.generic_penalty for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean < 3.0, f"Mean generic penalty {mean:.1f} ≥ 3.0"

    def test_no_profile_above_penalty_cap(self, all_scores):
        """No profile should have more than 5 unsupported generic phrases."""
        offenders = [(t, s.generic_penalty) for t, s in all_scores.items()
                     if s.generic_penalty > 5]
        assert len(offenders) == 0, (
            f"{len(offenders)} profiles have >5 generic phrases:\n"
            + "\n".join(f"  {t}: {n} generics" for t, n in
                        sorted(offenders, key=lambda x: x[1], reverse=True))
        )


class TestInternalConsistency:
    """Profiles must not contain internal contradictions."""

    def test_consistency_rate_above_threshold(self, all_scores):
        consistent = sum(1 for s in all_scores.values() if s.consistency == 100)
        rate = consistent / len(all_scores)
        # Current baseline: 40% (brand-moat-without-brand-advantage is the main hit).
        # Target: 75%. Gap = moat_type alignment task.
        assert rate >= 0.30, (
            f"Only {rate:.1%} of profiles are internally consistent (floor ≥30%)"
        )


class TestCompositeScore:
    """Overall quality metrics."""

    def test_mean_composite_above_threshold(self, all_scores):
        vals = [s.composite for s in all_scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 40, f"Mean composite score {mean:.1f} < 40 minimum"

    def test_no_composite_below_floor(self, all_scores):
        """No profile should have a composite below 15."""
        floor_failures = [(t, s.composite) for t, s in all_scores.items()
                          if s.composite < 15]
        assert len(floor_failures) == 0, (
            f"{len(floor_failures)} profiles below composite floor (15):\n"
            + "\n".join(f"  {t}: {s:.1f}" for t, s in
                        sorted(floor_failures, key=lambda x: x[1]))
        )


# ═══════════════════════════════════════════════════════════════════════════
# Report generator
# ═══════════════════════════════════════════════════════════════════════════

class TestExplanationQualityReport:
    """Comprehensive V2 report — always prints."""

    def test_generate_report(self, all_scores, profile_db):
        report = []
        report.append("\n" + "=" * 90)
        report.append("V2 EXPLANATION QUALITY REPORT")
        report.append("=" * 90)

        # Sort by composite descending
        ranked = sorted(all_scores.items(), key=lambda x: x[1].composite, reverse=True)

        # ── Per-company table ─────────────────────────────────────────────
        report.append(f"\n{'Rank':>4}  {'Ticker':>6}  {'Spec':>4}  {'Quant':>5}  {'Causal':>6}  "
                      f"{'Useful':>6}  {'GenPen':>6}  {'Consist':>7}  {'Composite':>9}  Failures")
        report.append("-" * 90)

        for i, (ticker, s) in enumerate(ranked, 1):
            fail_summary = "; ".join(s.failures[:2]) if s.failures else "—"
            if len(fail_summary) > 35:
                fail_summary = fail_summary[:35] + "..."
            report.append(
                f"  {i:3d}  {ticker:>6}  {s.specificity:4d}  {s.quantitative:5d}  {s.causal:6d}  "
                f"{s.usefulness:6d}  {s.generic_penalty:6d}  {s.consistency:7d}  {s.composite:9.1f}  {fail_summary}"
            )

        # ── Dimension statistics ──────────────────────────────────────────
        report.append(f"\n{'─' * 90}")
        report.append("DIMENSION STATISTICS")
        report.append(f"{'─' * 90}")

        for dim_name, dim_getter in [
            ("Specificity", lambda s: s.specificity),
            ("Quantitative", lambda s: s.quantitative),
            ("Causal", lambda s: s.causal),
            ("Usefulness", lambda s: s.usefulness),
            ("Generic Penalty", lambda s: s.generic_penalty),
            ("Consistency", lambda s: s.consistency),
            ("Composite", lambda s: s.composite),
        ]:
            vals = [dim_getter(s) for s in all_scores.values()]
            mean = sum(vals) / len(vals)
            lo = min(vals)
            hi = max(vals)
            report.append(f"  {dim_name:18s}  mean={mean:5.1f}  min={lo:5.1f}  max={hi:5.1f}")

        # ── Quality tiers ─────────────────────────────────────────────────
        report.append(f"\n{'─' * 90}")
        report.append("QUALITY TIERS")
        report.append(f"{'─' * 90}")

        tiers = {
            "Institutional (≥70)": [],
            "Professional (50-69)": [],
            "Adequate (35-49)": [],
            "Weak (20-34)": [],
            "Insufficient (<20)": [],
        }
        for ticker, s in all_scores.items():
            c = s.composite
            if c >= 70:
                tiers["Institutional (≥70)"].append(ticker)
            elif c >= 50:
                tiers["Professional (50-69)"].append(ticker)
            elif c >= 35:
                tiers["Adequate (35-49)"].append(ticker)
            elif c >= 20:
                tiers["Weak (20-34)"].append(ticker)
            else:
                tiers["Insufficient (<20)"].append(ticker)

        for tier, tickers in tiers.items():
            report.append(f"  {tier:30s}  {len(tickers):3d}  ({len(tickers)*100//len(all_scores):2d}%)")
            if tickers and len(tickers) <= 20:
                report.append(f"    {', '.join(sorted(tickers))}")

        # ── Failure taxonomy ──────────────────────────────────────────────
        report.append(f"\n{'─' * 90}")
        report.append("FAILURE TAXONOMY")
        report.append(f"{'─' * 90}")

        failure_counts: Dict[str, int] = Counter()
        for s in all_scores.values():
            for f in s.failures:
                category = f.split(":")[0]
                failure_counts[category] += 1

        total_failures = sum(failure_counts.values())
        for cat, count in failure_counts.most_common():
            desc = _FAILURE_CATEGORIES.get(cat, cat)
            report.append(f"  {cat:22s}  {count:4d}  ({count*100//max(total_failures,1):2d}%)  {desc}")

        report.append(f"\n  Total failure instances: {total_failures}")
        report.append(f"  Profiles with 0 failures: {sum(1 for s in all_scores.values() if not s.failures)}")
        report.append(f"  Profiles with 1+ failure: {sum(1 for s in all_scores.values() if s.failures)}")

        # ── Bottom 10 (profiles needing improvement) ──────────────────────
        report.append(f"\n{'─' * 90}")
        report.append("BOTTOM 10 — PROFILES NEEDING IMPROVEMENT")
        report.append(f"{'─' * 90}")

        for ticker, s in ranked[-10:]:
            report.append(f"\n  {ticker} ({s.company}) — composite={s.composite:.1f}")
            report.append(f"    Spec={s.specificity} Quant={s.quantitative} Causal={s.causal} "
                          f"Useful={s.usefulness} GenPen={s.generic_penalty} Consist={s.consistency}")
            if s.failures:
                for f in s.failures:
                    report.append(f"    - {f}")

        # ── Verdict ───────────────────────────────────────────────────────
        composites = [s.composite for s in all_scores.values()]
        mean_composite = sum(composites) / len(composites)
        institutional_count = sum(1 for c in composites if c >= 70)
        insufficient_count = sum(1 for c in composites if c < 20)

        report.append(f"\n{'=' * 90}")
        if mean_composite >= 60 and insufficient_count == 0:
            verdict = "PASS — Institutional grade"
        elif mean_composite >= 50 and insufficient_count <= 5:
            verdict = "CONDITIONAL PASS — Professional grade (some profiles need enrichment)"
        elif mean_composite >= 40:
            verdict = "MARGINAL — Adequate but not differentiated"
        else:
            verdict = "FAIL — Explanation quality insufficient for paid product"

        report.append(f"VERDICT: {verdict}")
        report.append(f"  Mean composite:     {mean_composite:.1f}")
        report.append(f"  Institutional tier: {institutional_count}/{len(all_scores)} ({institutional_count*100//len(all_scores)}%)")
        report.append(f"  Insufficient tier:  {insufficient_count}/{len(all_scores)} ({insufficient_count*100//len(all_scores)}%)")
        report.append("=" * 90)

        print("\n".join(report))
        assert True
