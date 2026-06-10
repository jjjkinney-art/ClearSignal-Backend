"""
Phase 9F — Historical Evidence Engine.

Retrieves the most relevant historical analogs for the current analysis
by scoring against a SetupFingerprint derived from concern_tags, mechanisms,
and contextual signals in the thesis.

Design constraints:
  - NEVER injects analogs into the synthesis prompt (no LLM token impact).
  - Post-dispatch only: attaches historical_evidence to the final response.
  - Hard floor: returns [] when best score < RELEVANCE_FLOOR ("no analog" is valid).
  - Diversity: at most one analog per mechanism; returns top-3 distinct mechanisms.
  - Match on setup and mechanism — never on outcome alone.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELEVANCE_FLOOR = 0.40   # scores below this → return []
TOP_K = 3                # maximum analogs returned (one per mechanism)
DISANALOGY_PENALTY = 0.05  # flat penalty applied to every analog (forces honesty check)

# ---------------------------------------------------------------------------
# Concern-tag → primary mechanism mapping
# ---------------------------------------------------------------------------

# Tags that map to a primary mechanism trigger that mechanism at 1.0 weight.
# Tags listed under "secondary" produce 0.7 weight via the mechanism scoring.
# "amplifier" tags have no mechanism but boost concern_tag_jaccard naturally.

_TAG_TO_PRIMARY_MECHANISM: Dict[str, str] = {
    "capex_cycle":          "infrastructure_overbuild",
    "supply_chain_risk":    "inventory_channel_correction",
    "macro_slowdown_risk":  "demand_air_pocket",
    "interest_rate_risk":   "rate_shock",
    "cre_credit_risk":      "credit_event",
    "valuation_risk":       "multiple_compression",
    "competitive_risk":     "competitive_displacement",
    "regulatory_risk":      "regulatory_break",
    "geopolitical_risk":    "regulatory_break",
    "att_privacy_risk":     "regulatory_break",
    "ai_adoption_risk":     "hypergrowth_deceleration",
    "currency_risk":        "commodity_shock",
    # amplifier / outcome tags — no primary mechanism
    # "concentration_risk":  no mechanism
    # "margin_pressure":     no mechanism
}

_TAG_TO_SECONDARY_MECHANISM: Dict[str, str] = {
    "capex_cycle":          "demand_air_pocket",
    "supply_chain_risk":    "demand_air_pocket",
    "macro_slowdown_risk":  "inventory_channel_correction",
    "interest_rate_risk":   "credit_event",
    "cre_credit_risk":      "rate_shock",
    "ai_adoption_risk":     "competitive_displacement",
    "competitive_risk":     "hypergrowth_deceleration",
}

# Mechanism siblings (partial credit: 0.5 on mechanism match)
_MECHANISM_SIBLINGS: Dict[str, str] = {
    "infrastructure_overbuild":     "inventory_channel_correction",
    "inventory_channel_correction": "infrastructure_overbuild",
    "demand_air_pocket":            "inventory_channel_correction",
    "multiple_compression":         "hypergrowth_deceleration",
    "hypergrowth_deceleration":     "multiple_compression",
    "rate_shock":                   "credit_event",
    "credit_event":                 "rate_shock",
}

# ---------------------------------------------------------------------------
# SetupFingerprint
# ---------------------------------------------------------------------------

@dataclass
class SetupFingerprint:
    """Derived at request time from the thesis and question context."""

    concern_tags: List[str] = field(default_factory=list)    # canonical tag names
    inferred_mechanisms: List[str] = field(default_factory=list)  # derived from tags
    ticker: Optional[str] = None
    sector: Optional[str] = None
    business_model: Optional[str] = None
    valuation_regime: Optional[str] = None   # peak_multiple | compressed | neutral | ""
    growth_phase: Optional[str] = None       # hypergrowth | deceleration | mature | ""
    macro_regime: Optional[str] = None       # hiking | easing | inversion | neutral | ""
    question_text: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_fingerprint(
    question: str,
    thesis_dict: dict,
    ticker: Optional[str] = None,
) -> SetupFingerprint:
    """Build a SetupFingerprint from an InvestmentThesis dict and the question."""
    concern_tags = _extract_concern_tags(thesis_dict)
    mechanisms = _infer_mechanisms(concern_tags, question, thesis_dict)
    sector, biz_model = _infer_sector_biz(thesis_dict, ticker)
    val_regime = _infer_valuation_regime(question, thesis_dict)
    growth_phase = _infer_growth_phase(question, thesis_dict)
    macro_regime = _infer_macro_regime(question, thesis_dict)

    return SetupFingerprint(
        concern_tags=concern_tags,
        inferred_mechanisms=mechanisms,
        ticker=ticker,
        sector=sector,
        business_model=biz_model,
        valuation_regime=val_regime,
        growth_phase=growth_phase,
        macro_regime=macro_regime,
        question_text=question,
    )


def retrieve_historical_analogs(
    analogs,
    fingerprint: SetupFingerprint,
    floor: float = RELEVANCE_FLOOR,
    top_k: int = TOP_K,
) -> List[dict]:
    """Score all analogs against the fingerprint, apply floor, enforce diversity.

    Args:
        analogs: List[HistoricalAnalog] ORM objects (from get_all_analogs).
        fingerprint: SetupFingerprint derived from the current query.
        floor: minimum score threshold.
        top_k: max results (one per mechanism).

    Returns:
        List of dicts (serialisable payload for the response), [] if no strong match.
    """
    if not analogs or not fingerprint:
        return []

    scored: List[Tuple[float, object]] = []
    for analog in analogs:
        score = _score_analog(analog, fingerprint)
        if score >= floor:
            scored.append((score, analog))

    if not scored:
        return []

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Diversity: at most one analog per mechanism, take top_k
    seen_mechanisms: set = set()
    results = []
    for score, analog in scored:
        mech = analog.mechanism
        if mech in seen_mechanisms:
            continue
        seen_mechanisms.add(mech)
        results.append(_analog_to_dict(score, analog))
        if len(results) >= top_k:
            break

    return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_analog(analog, fp: SetupFingerprint) -> float:
    """Compute composite relevance score (0–1) for one analog."""

    # 1. Concern-tag Jaccard (weight 0.40)
    analog_tags = set(analog.concern_tags or [])
    fp_tags = set(fp.concern_tags or [])
    if analog_tags or fp_tags:
        intersection = len(analog_tags & fp_tags)
        union = len(analog_tags | fp_tags)
        tag_score = intersection / union if union else 0.0
    else:
        tag_score = 0.0

    # 2. Mechanism match (weight 0.30)
    # Best mechanism match across all inferred mechanisms
    mech_score = 0.0
    for inferred_mech in (fp.inferred_mechanisms or []):
        ms = _mechanism_score(inferred_mech, analog.mechanism)
        if ms > mech_score:
            mech_score = ms
    # Also check if any concern tags directly map to analog mechanism
    for tag in fp.concern_tags:
        primary = _TAG_TO_PRIMARY_MECHANISM.get(tag)
        if primary:
            ms = _mechanism_score(primary, analog.mechanism)
            if ms > mech_score:
                mech_score = ms

    # 3. Setup match: valuation_regime + growth_phase (weight 0.15)
    setup_score = 0.0
    if fp.valuation_regime and analog.valuation_regime:
        if fp.valuation_regime == analog.valuation_regime:
            setup_score += 0.075
    if fp.growth_phase and analog.growth_phase:
        if fp.growth_phase == analog.growth_phase:
            setup_score += 0.075

    # 4. Sector / business_model proximity (weight 0.10)
    context_score = 0.0
    if fp.sector and analog.sector and fp.sector == analog.sector:
        context_score += 0.05
    if fp.business_model and analog.business_model and fp.business_model == analog.business_model:
        context_score += 0.05

    # 5. Macro regime agreement (weight 0.05)
    macro_score = 0.0
    if fp.macro_regime and analog.macro_regime:
        if fp.macro_regime == analog.macro_regime:
            macro_score = 0.05

    # Weighted composite
    raw = (
        0.40 * tag_score +
        0.30 * mech_score +
        0.15 * setup_score / 0.15 * 0.15 +   # normalised within weight
        0.10 * context_score / 0.10 * 0.10 + # normalised within weight
        0.05 * macro_score / 0.05 * 0.05     # normalised within weight
    )
    # Simplify: weights already encoded in constants above
    raw = (
        0.40 * tag_score
        + 0.30 * mech_score
        + setup_score          # already at 0–0.15
        + context_score        # already at 0–0.10
        + macro_score          # already at 0–0.05
    )

    # Quality boost: strong analogs get small uplift; does not cross floor alone
    if getattr(analog, "quality_rating", "") == "strong":
        raw += 0.02

    # Flat disanalogy penalty (structural honesty tax)
    raw -= DISANALOGY_PENALTY

    return max(0.0, min(1.0, raw))


def _mechanism_score(query_mech: str, analog_mech: str) -> float:
    """1.0 primary match, 0.5 sibling, 0.0 none."""
    if not query_mech or not analog_mech:
        return 0.0
    if query_mech == analog_mech:
        return 1.0
    sibling = _MECHANISM_SIBLINGS.get(query_mech)
    if sibling and sibling == analog_mech:
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Fingerprint construction helpers
# ---------------------------------------------------------------------------

def _extract_concern_tags(thesis: dict) -> List[str]:
    """Extract concern tags from the thesis concern_tags / key_risks / macro_sensitivity."""
    tags: List[str] = []

    # Phase 9C concern_tags stored on the thesis (list of strings or dicts)
    raw_tags = thesis.get("concern_tags") or []
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, str):
                tags.append(t)
            elif isinstance(t, dict):
                name = t.get("tag") or t.get("name") or t.get("tag_name") or ""
                if name:
                    tags.append(name)

    # Also check macro_sensitivity keys — they often overlap with canonical tags
    macro = thesis.get("macro_sensitivity") or {}
    if isinstance(macro, dict):
        for k in macro:
            canonical = _normalize_to_canonical_tag(k)
            if canonical and canonical not in tags:
                tags.append(canonical)

    return list(dict.fromkeys(tags))  # deduplicate, preserve order


_CANONICAL_TAGS = set(_TAG_TO_PRIMARY_MECHANISM.keys()) | {"concentration_risk", "margin_pressure"}

_ALIAS_MAP: Dict[str, str] = {
    "rates":              "interest_rate_risk",
    "interest_rates":     "interest_rate_risk",
    "rate":               "interest_rate_risk",
    "capex":              "capex_cycle",
    "competition":        "competitive_risk",
    "regulation":         "regulatory_risk",
    "geopolitics":        "geopolitical_risk",
    "supply_chain":       "supply_chain_risk",
    "macro":              "macro_slowdown_risk",
    "currency":           "currency_risk",
    "credit":             "cre_credit_risk",
    "ai_adoption":        "ai_adoption_risk",
    "att":                "att_privacy_risk",
    "valuation":          "valuation_risk",
    "concentration":      "concentration_risk",
    "margin":             "margin_pressure",
}


def _normalize_to_canonical_tag(key: str) -> Optional[str]:
    k = key.lower().replace("-", "_").replace(" ", "_")
    if k in _CANONICAL_TAGS:
        return k
    return _ALIAS_MAP.get(k)


def _infer_mechanisms(tags: List[str], question: str, thesis: dict) -> List[str]:
    """Derive candidate mechanisms from concern tags and question text."""
    mechs = []
    for tag in tags:
        pm = _TAG_TO_PRIMARY_MECHANISM.get(tag)
        if pm and pm not in mechs:
            mechs.append(pm)
        sm = _TAG_TO_SECONDARY_MECHANISM.get(tag)
        if sm and sm not in mechs:
            mechs.append(sm)

    # Question-text heuristics
    q = question.lower()
    _kw_to_mech = [
        (["break", "bull case", "risk", "downside", "what could go wrong"], None),  # general
        (["inventory", "channel", "oversupply", "supply glut"],              "inventory_channel_correction"),
        (["overbuild", "overbuilt", "capex cycle", "buildout"],              "infrastructure_overbuild"),
        (["air pocket", "demand drop", "demand collapse", "pull-forward"],   "demand_air_pocket"),
        (["multiple", "de-rate", "re-rate", "valuation compress"],           "multiple_compression"),
        (["deceleration", "growth miss", "first miss", "growth stall"],      "hypergrowth_deceleration"),
        (["displace", "competition", "market share loss", "competitor"],      "competitive_displacement"),
        (["rates", "interest rate", "rate hike", "rate shock", "duration"],  "rate_shock"),
        (["credit", "default", "bank run", "balance sheet"],                 "credit_event"),
        (["regulation", "antitrust", "banned", "restricted"],                "regulatory_break"),
        (["commodity", "oil", "energy price", "raw material"],               "commodity_shock"),
    ]
    for keywords, mech in _kw_to_mech:
        if mech and any(kw in q for kw in keywords) and mech not in mechs:
            mechs.append(mech)

    return mechs


_SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "technology":            ["tech", "software", "hardware", "cloud", "ai", "semiconductor", "chip"],
    "financials":            ["bank", "financial", "credit", "insurance", "fintech", "reit", "mortgage"],
    "healthcare":            ["pharma", "biotech", "healthcare", "medical", "drug", "therapy"],
    "consumer_discretionary": ["retail", "consumer", "e-commerce", "fashion", "auto"],
    "energy":                ["oil", "gas", "energy", "crude", "refin"],
    "industrials":           ["industrial", "manufacturing", "aerospace", "defense", "transport"],
}

_BIZ_MODEL_KEYWORDS: Dict[str, List[str]] = {
    "saas":                    ["saas", "software as a service", "recurring revenue", "arr", "mrr"],
    "semiconductor_fabless":   ["fabless", "gpu", "chip design", "arm"],
    "semiconductor_manufacturer": ["foundry", "wafer", "tsmc", "memory", "dram", "nand"],
    "infrastructure_supplier": ["networking", "switch", "router", "interconnect"],
    "internet_platform":       ["platform", "social", "search", "marketplace", "ad"],
    "fintech_platform":        ["payment", "fintech", "checkout", "wallet"],
    "financial_intermediary":  ["bank", "lender", "broker", "dealer", "reit"],
    "consumer_hardware":       ["hardware", "device", "consumer electronics"],
    "integrated_oil":          ["integrated", "upstream", "downstream", "refining"],
}


def _infer_sector_biz(thesis: dict, ticker: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Try to infer sector and business model from thesis text."""
    text = " ".join([
        str(thesis.get("bull_thesis", "")),
        str(thesis.get("bear_thesis", "")),
        str(thesis.get("conclusion", "")),
        str(thesis.get("company_name", "")),
        str(ticker or ""),
    ]).lower()

    sector = None
    for s, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            sector = s
            break

    biz_model = None
    for b, keywords in _BIZ_MODEL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            biz_model = b
            break

    return sector, biz_model


def _infer_valuation_regime(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("conclusion", ""))).lower()
    if any(kw in text for kw in ["overvalued", "peak multiple", "expensive", "bubble", "frothy", "60x", "50x", "40x"]):
        return "peak_multiple"
    if any(kw in text for kw in ["undervalued", "cheap", "compressed", "low multiple", "discounted"]):
        return "compressed"
    # Heuristic from confidence
    confidence = float(thesis.get("confidence_score") or 0)
    if confidence > 0.75:
        return "peak_multiple"
    return None


def _infer_growth_phase(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("bull_thesis", "")) + " " + str(thesis.get("conclusion", ""))).lower()
    if any(kw in text for kw in ["hypergrowth", "hyper-growth", "triple digit", "200%", "150%", "100% growth"]):
        return "hypergrowth"
    if any(kw in text for kw in ["decelerat", "slowdown", "growth missing", "growth miss", "mature"]):
        return "deceleration"
    if any(kw in text for kw in ["mature", "steady state", "single digit growth"]):
        return "mature"
    return None


def _infer_macro_regime(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("macro_sensitivity", ""))).lower()
    if any(kw in text for kw in ["rate hike", "hiking", "tightening", "fed raise", "rising rates"]):
        return "hiking"
    if any(kw in text for kw in ["rate cut", "easing", "dovish", "fed cut", "falling rates"]):
        return "easing"
    if any(kw in text for kw in ["inversion", "inverted", "yield curve inverted"]):
        return "inversion"
    return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _analog_to_dict(score: float, analog) -> dict:
    """Convert HistoricalAnalog ORM object to the response payload dict."""
    return {
        "label":                analog.label,
        "episode":              analog.episode,
        "entity_ticker":        analog.entity_ticker,
        "sector":               analog.sector,
        "mechanism":            analog.mechanism,
        "quality_rating":       analog.quality_rating,
        "drawdown_pct":         analog.drawdown_pct,
        "time_to_trough_days":  analog.time_to_trough_days,
        "time_to_recover_days": analog.time_to_recover_days,
        "outcome_summary":      analog.outcome_summary,
        "why_relevant":         analog.why_relevant,
        "disanalogy":           analog.disanalogy,
        "base_rate_note":       analog.base_rate_note,
        "data_confidence":      analog.data_confidence,
        "relevance_score":      round(score, 4),
    }
